"""鉴权依赖 —— 需求文档 §13（JWT / RBAC）。

放在 Controller 层的只有「怎么从 HTTP 请求里取出身份」这件事；
真正的权限判定规则在 `dw_domain.access_control`（纯函数、可单测）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from dw_domain.errors import TokenError
from dw_domain.security import decode_access_token
from dw_infrastructure.config import Settings
from dw_infrastructure.db import Database
from dw_schemas.iam import PermissionCode, UserIdentity
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.errors import AuthenticationRequiredError, PermissionDeniedError

# auto_error=False：由我们自己把它转成统一错误信封，而不是让 Starlette 返回裸 403
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="JWT")


def current_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """每个请求一个会话，退出即结束事务（正常提交 / 异常回滚）。"""
    database: Database = request.app.state.database
    async with database.session() as session:
        yield session


async def current_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserIdentity:
    """从 Bearer 令牌解析身份。

    令牌内已包含 roles / permissions，因此鉴权不需要查库；
    需要「最新」状态（例如账号已被停用）的端点走 `/auth/me`，那里会回查数据库。
    """
    if credentials is None:
        raise AuthenticationRequiredError("缺少 Bearer 令牌")
    try:
        return decode_access_token(
            credentials.credentials, secret_key=current_settings(request).secret_key
        )
    except TokenError as exc:
        # 过期与伪造对外统一为「令牌无效」，避免给攻击者提供有用反馈
        raise AuthenticationRequiredError("令牌无效或已过期") from exc


def require_permissions(*codes: PermissionCode):
    """tool scope 校验依赖工厂（§13 Tool Scope）。"""

    async def dependency(
        identity: UserIdentity = Depends(current_identity),
    ) -> UserIdentity:
        if identity.is_admin:
            return identity
        missing = [code.value for code in codes if code not in identity.permissions]
        if missing:
            raise PermissionDeniedError(f"缺少权限: {', '.join(missing)}")
        return identity

    return dependency
