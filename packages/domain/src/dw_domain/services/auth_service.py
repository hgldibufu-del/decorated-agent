"""认证应用服务 —— 需求文档 §13。

职责：校验凭据 → 签发令牌。**不接触 HTTP**（那是 apps/api 的事）。
"""

from __future__ import annotations

from dw_infrastructure.config import Settings
from dw_schemas.iam import LoginRequest, TokenResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dw_domain.errors import InactiveUserError, InvalidCredentialsError
from dw_domain.models.iam import User
from dw_domain.repositories.iam import UserRepository
from dw_domain.security import create_access_token, verify_password


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._users = UserRepository(session)

    async def authenticate(self, payload: LoginRequest) -> tuple[User, TokenResponse]:
        """成功返回 (用户, 令牌)；失败抛领域异常。

        注意：邮箱不存在与口令错误对外返回**同一句提示**，
        否则就给了攻击者枚举注册邮箱的能力。
        """
        user = await self._users.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise InvalidCredentialsError("邮箱或口令错误")
        if not user.is_active:
            raise InactiveUserError("账号已停用")
        return user, self.issue_token(user)

    def issue_token(self, user: User) -> TokenResponse:
        token, expires_in = create_access_token(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            roles=user.role_names(),
            permissions=user.permission_codes(),
            secret_key=self._settings.secret_key,
            expires_minutes=self._settings.access_token_expire_minutes,
        )
        return TokenResponse(access_token=token, expires_in=expires_in)
