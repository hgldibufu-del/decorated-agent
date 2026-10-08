"""口令散列与 JWT —— 需求文档 §13、§24。

刻意的选择：

* **口令散列不引入 argon2/passlib**：用标准库 `hashlib.pbkdf2_hmac`
  （PBKDF2-HMAC-SHA256 + 每用户随机盐 + 600k 迭代）。满足当前基线且不增加密码学依赖；
  将来换 argon2id 只需替换本文件中 `hash_password` / `verify_password` 的实现，
  调用方与存储格式头都可平滑演进（格式串已包含算法标识）。
* **令牌字段包含角色与权限**：让鉴权不必每次查库。
  代价是撤销不能立即生效 → 由较短的 `ACCESS_TOKEN_EXPIRE_MINUTES` 兜底（见 docs/architecture.md）。
* **验签算法白名单**：显式只允许 HS256，防止 alg 混淆（把 alg 改成 none 的经典攻击）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from dw_schemas.iam import PermissionCode, RoleName, UserIdentity

from dw_domain.errors import TokenExpiredError, TokenInvalidError

ALGORITHM = "HS256"
ALLOWED_ALGORITHMS = frozenset({"HS256"})

PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
HASH_PREFIX = "pbkdf2_sha256"

TOKEN_CLAIM_ROLES = "roles"
TOKEN_CLAIM_PERMISSIONS = "permissions"
TOKEN_CLAIM_EMAIL = "email"
TOKEN_CLAIM_NAME = "name"


# -----------------------------------------------------------------------------
# 口令
# -----------------------------------------------------------------------------
def hash_password(raw_password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """生成 `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`。"""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(raw_password, salt, iterations)
    return "$".join(
        [
            HASH_PREFIX,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(raw_password: str, encoded: str) -> bool:
    """用 hmac.compare_digest 做定长比较，避免时序侧信道。"""
    try:
        prefix, iterations_text, salt_b64, digest_b64 = encoded.split("$")
        if prefix != HASH_PREFIX:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        # 存储格式损坏：视为验证失败，不抛异常（避免把内部状态暴露给调用方）
        return False

    actual = _derive(raw_password, salt, iterations)
    return hmac.compare_digest(actual, expected)


def password_needs_upgrade(encoded: str, *, iterations: int = PBKDF2_ITERATIONS) -> bool:
    """迭代次数低于当前基线时应在下次登录时重新散列。"""
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != HASH_PREFIX:
        return True
    try:
        return int(parts[1]) < iterations
    except ValueError:
        return True


def _derive(raw_password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt, iterations, dklen=32)


# -----------------------------------------------------------------------------
# JWT
# -----------------------------------------------------------------------------
def create_access_token(
    *,
    user_id: UUID,
    email: str,
    full_name: str,
    roles: list[str],
    permissions: list[str],
    secret_key: str,
    expires_minutes: int,
    now: datetime | None = None,
) -> tuple[str, int]:
    """签发令牌，返回 (token, expires_in_seconds)。"""
    current = now or datetime.now(timezone.utc)
    expires_in_seconds = expires_minutes * 60
    payload = {
        "sub": str(user_id),
        "iat": current,
        "exp": current + timedelta(seconds=expires_in_seconds),
        TOKEN_CLAIM_EMAIL: email,
        TOKEN_CLAIM_NAME: full_name,
        TOKEN_CLAIM_ROLES: roles,
        TOKEN_CLAIM_PERMISSIONS: permissions,
    }
    token = jwt.encode(payload, secret_key, algorithm=ALGORITHM)
    return token, expires_in_seconds


def decode_access_token(token: str, *, secret_key: str) -> UserIdentity:
    """校验并解析令牌。

    失败一律转成领域异常，不允许把 PyJWT 的异常类型泄漏到接入层。
    """
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=list(ALLOWED_ALGORITHMS),
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError(f"令牌无效: {exc}") from exc

    roles = _string_list(payload.get(TOKEN_CLAIM_ROLES))
    permissions = _string_list(payload.get(TOKEN_CLAIM_PERMISSIONS))

    return UserIdentity(
        user_id=UUID(payload["sub"]),
        email=str(payload.get(TOKEN_CLAIM_EMAIL, "")),
        full_name=str(payload.get(TOKEN_CLAIM_NAME, "")),
        roles=[RoleName(role) for role in roles if _is_known(RoleName, role)],
        permissions=[
            PermissionCode(code) for code in permissions if _is_known(PermissionCode, code)
        ],
    )


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _is_known(enum_cls: type[RoleName] | type[PermissionCode], value: str) -> bool:
    try:
        enum_cls(value)
    except ValueError:
        # 令牌里出现未知角色/权限（可能是旧版本签发）：忽略而不是整体失败
        return False
    return True
