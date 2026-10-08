"""口令散列与 JWT 单测（不需要数据库）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from dw_domain.errors import TokenExpiredError, TokenInvalidError
from dw_domain.security import (
    PBKDF2_ITERATIONS,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_upgrade,
    verify_password,
)
from dw_schemas.iam import PermissionCode, RoleName

SECRET = "unit-test-secret-key-not-a-real-one"


def issue(**overrides) -> str:
    kwargs = {
        "user_id": uuid4(),
        "email": "pm@dw.local",
        "full_name": "测试用户",
        "roles": [RoleName.PROJECT_MANAGER.value],
        "permissions": [PermissionCode.PROJECT_READ.value, PermissionCode.PROJECT_WRITE.value],
        "secret_key": SECRET,
        "expires_minutes": 30,
    }
    kwargs.update(overrides)
    token, _ = create_access_token(**kwargs)
    return token


# -----------------------------------------------------------------------------
# 口令
# -----------------------------------------------------------------------------
def test_hash_format_contains_algorithm_iterations_and_salt():
    encoded = hash_password("Passw0rd!")
    parts = encoded.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) == PBKDF2_ITERATIONS


def test_same_password_produces_different_hashes():
    """每次散列必须使用新盐，否则彩虹表可一次反推全体用户。"""
    assert hash_password("Passw0rd!") != hash_password("Passw0rd!")


def test_verify_password_accepts_correct_password():
    encoded = hash_password("Passw0rd!")
    assert verify_password("Passw0rd!", encoded) is True


def test_verify_password_rejects_wrong_password_and_garbage():
    encoded = hash_password("Passw0rd!")
    assert verify_password("wrong", encoded) is False
    assert verify_password("Passw0rd!", "not-a-hash") is False
    assert verify_password("Passw0rd!", "") is False


def test_low_iteration_hash_needs_upgrade():
    old = hash_password("Passw0rd!", iterations=1000)
    assert password_needs_upgrade(old) is True
    assert password_needs_upgrade(hash_password("Passw0rd!")) is False


# -----------------------------------------------------------------------------
# JWT
# -----------------------------------------------------------------------------
def test_token_roundtrip_keeps_identity():
    user_id = uuid4()
    token, expires_in = create_access_token(
        user_id=user_id,
        email="pm@dw.local",
        full_name="王经理",
        roles=[RoleName.PROJECT_MANAGER.value],
        permissions=[PermissionCode.PROJECT_READ.value],
        secret_key=SECRET,
        expires_minutes=30,
    )

    identity = decode_access_token(token, secret_key=SECRET)
    assert expires_in == 30 * 60
    assert identity.user_id == user_id
    assert identity.email == "pm@dw.local"
    assert identity.permissions == [PermissionCode.PROJECT_READ]
    assert identity.is_admin is False


def test_admin_flag_is_derived_from_roles():
    token = issue(roles=[RoleName.ADMIN.value])
    assert decode_access_token(token, secret_key=SECRET).is_admin is True


def test_expired_token_is_rejected():
    created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    token = issue(expires_minutes=1, now=created_at)
    with pytest.raises(TokenExpiredError):
        decode_access_token(token, secret_key=SECRET)


def test_tampered_signature_is_rejected():
    token = issue()
    tampered = f"{token[:-4]}aaaa"
    with pytest.raises(TokenInvalidError):
        decode_access_token(tampered, secret_key=SECRET)


def test_token_signed_with_another_secret_is_rejected():
    token = issue(secret_key="another-secret-key-that-is-at-least-32-bytes")
    with pytest.raises(TokenInvalidError):
        decode_access_token(token, secret_key=SECRET)


def test_none_algorithm_attack_is_rejected():
    """经典攻击：把 alg 改成 none 后去掉签名再提交。"""
    payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "email": "attacker@dw.local",
        "roles": [RoleName.ADMIN.value],
        "permissions": [],
    }
    unsigned = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(TokenInvalidError):
        decode_access_token(unsigned, secret_key=SECRET)


def test_unknown_roles_in_token_are_dropped_not_failed():
    """旧版本签发的令牌可能带上已废弃的角色；应忽略而非整体拒绝。"""
    token = issue(roles=[RoleName.VIEWER.value, "retired_role"])
    identity = decode_access_token(token, secret_key=SECRET)
    assert identity.roles == [RoleName.VIEWER]
