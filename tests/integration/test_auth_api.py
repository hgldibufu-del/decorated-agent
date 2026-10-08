"""认证端到端：HTTP → 应用服务 → 真实 PostgreSQL。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dw_domain.security import create_access_token
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.iam import PermissionCode, RoleName
from sqlalchemy import text


async def test_login_returns_token(make_user, client):
    user = await make_user(role=RoleName.PROJECT_MANAGER)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert body["access_token"].count(".") == 2  # JWT 三段结构


async def test_me_returns_roles_and_permissions_from_roles(auth_headers, client):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roles"] == [RoleName.PROJECT_MANAGER.value]
    assert PermissionCode.PROJECT_READ.value in body["permissions"]
    assert PermissionCode.PROJECT_WRITE.value in body["permissions"]
    assert body["is_active"] is True


async def test_missing_token_is_401(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert response.json()["retryable"] is False


async def test_garbage_token_is_401(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_expired_token_is_401(make_user, client):
    """令牌未过期不等于身份仍有效：过期令牌必须拒绝。"""
    user = await make_user(role=RoleName.VIEWER)
    settings = get_settings()
    token, _ = create_access_token(
        user_id=user["id"],  # type: ignore[arg-type]
        email=user["email"],
        full_name="过期测试",
        roles=[RoleName.VIEWER.value],
        permissions=[PermissionCode.PROJECT_READ.value],
        secret_key=settings.secret_key,
        expires_minutes=1,
        now=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_wrong_password_is_401(make_user, client):
    user = await make_user()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "definitely-wrong"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_unknown_email_gives_identical_message_as_wrong_password(client, make_user):
    """防止通过响应差异枚举已注册邮箱。"""
    user = await make_user()

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "nope"},
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "whoever@dw.local", "password": "nope"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["message"] == unknown_email.json()["message"]


async def test_inactive_user_token_stops_working_and_cannot_login(auth_headers, client):
    """账号停用后：令牌虽未过期也必须失效（/auth/me 回查数据库）。"""
    headers = await auth_headers(role=RoleName.VIEWER)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    database = Database.from_settings(get_settings())
    try:
        async with database.session() as session:
            await session.execute(
                text("UPDATE users SET is_active = false WHERE id = :id"),
                {"id": headers["user"]},
            )
    finally:
        await database.dispose()

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": headers["email"], "password": headers["password"]},
    )
    assert login.status_code == 401
