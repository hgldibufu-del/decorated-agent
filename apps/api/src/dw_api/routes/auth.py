"""认证路由 —— 需求文档 §13 / §21。"""

from __future__ import annotations

from dw_domain.repositories.iam import UserRepository
from dw_domain.services import AuthService
from dw_schemas.iam import (
    LoginRequest,
    PermissionCode,
    RoleName,
    TokenResponse,
    UserIdentity,
    UserSummary,
)
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import current_identity, current_settings, get_db_session
from dw_api.errors import AuthenticationRequiredError, ResourceNotFoundError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="登录并换取 JWT",
    responses={401: {"description": "邮箱或口令错误 / 账号停用"}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    service = AuthService(session, current_settings(request))
    _, token = await service.authenticate(payload)
    return token


@router.get(
    "/me",
    response_model=UserSummary,
    summary="当前登录用户及其角色权限",
    responses={401: {"description": "未认证或令牌失效"}},
)
async def read_me(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> UserSummary:
    """回查数据库而非直接返回令牌内容：账号被停用后令牌虽未过期也须立即失效。"""
    user = await UserRepository(session).get_by_id(identity.user_id)
    if user is None:
        raise ResourceNotFoundError("账号不存在")
    if not user.is_active:
        raise AuthenticationRequiredError("账号已停用")

    return UserSummary(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=[RoleName(name) for name in user.role_names()],
        permissions=[PermissionCode(code) for code in user.permission_codes()],
    )
