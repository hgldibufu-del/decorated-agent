"""集成测试夹具（需要真实 PostgreSQL）。

设计要点：

* 数据由**测试自己创建**，不依赖 seed —— 否则测试顺序或环境差异会导致结果不稳定；
* 每个夹具注册一个清理回调，按外键依赖顺序删除，避免污染后续用例；
* 每个辅助函数使用独立会话提交，模拟真实请求边界（而不是共享一个长事务，
  那样会把 ACL 相关的可见性问题掩盖掉）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from dw_api.app import create_app
from dw_domain.rbac_defaults import ROLE_PERMISSIONS
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_domain.repositories.iam import RoleRepository, UserRepository
from dw_domain.repositories.projects import (
    CustomerRepository,
    HouseRepository,
    ProjectRepository,
)
from dw_domain.security import hash_password
from dw_infrastructure.config import Settings, get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import PermissionCode, ProjectRole, RoleName
from fastapi.testclient import TestClient
from sqlalchemy import text

DEFAULT_PASSWORD = "Integration@123"

# 先删子表后删主表；项目→客户/房屋是 RESTRICT，顺序反了会报错而不是静默失败。
# agent_runs 放最前：它的子表（tasks / tool_calls / artifacts / approvals）都是 CASCADE。
DELETE_ORDER: tuple[tuple[str, str], ...] = (
    ("agent_runs", "id"),
    ("skills", "id"),
    ("agents", "id"),
    ("project_members", "project_id"),
    ("projects", "id"),
    ("houses", "id"),
    ("customers", "id"),
    ("user_roles", "user_id"),
    ("users", "id"),
)


@pytest.fixture
def api_settings() -> Settings:
    return Settings(app_env="testing", log_json=False, log_level="WARNING")


@pytest.fixture
def client(api_settings: Settings) -> Iterator[TestClient]:
    application = create_app(api_settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
async def cleaner() -> AsyncIterator[callable]:  # type: ignore[valid-type]
    scheduled: list[tuple[str, str, str]] = []
    yield lambda table, column, value: scheduled.append((table, column, value))
    await purge(scheduled)


async def purge(items: list[tuple[str, str, str]]) -> None:
    if not items:
        return
    database = Database.from_settings(get_settings())
    try:
        async with database.session() as session:
            for table, column in DELETE_ORDER:
                values = [value for (t, c, value) in items if (t, c) == (table, column)]
                for value in values:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE {column} = :value"),
                        {"value": str(value)},
                    )
    finally:
        await database.dispose()


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.fixture
def make_user(cleaner):
    async def factory(
        *,
        email: str | None = None,
        role: RoleName = RoleName.VIEWER,
        full_name: str = "集成用户",
        password: str = DEFAULT_PASSWORD,
        is_active: bool = True,
    ) -> dict[str, str]:
        address = email or f"{unique('user')}@dw.local"
        database = Database.from_settings(get_settings())
        user_id = None
        try:
            async with database.session() as session:
                roles = RoleRepository(session)
                await roles.ensure_permissions([permission.value for permission in PermissionCode])
                role_obj = await roles.ensure_role(role.value, description=role.value)
                await roles.bind_permissions(role_obj, ROLE_PERMISSIONS[role.value])
                user = await UserRepository(session).create(
                    email=address,
                    full_name=full_name,
                    hashed_password=hash_password(password),
                    is_active=is_active,
                )
                await roles.assign_role(user, role_obj)
                user_id = str(user.id)
        finally:
            await database.dispose()

        cleaner("user_roles", "user_id", user_id)
        cleaner("users", "id", user_id)
        return {"email": address, "password": password, "id": user_id}

    return factory


@pytest.fixture
def make_customer(cleaner):
    async def factory(*, name: str = "集成客户") -> dict[str, str]:
        database = Database.from_settings(get_settings())
        customer_id = None
        try:
            async with database.session() as session:
                customer = await CustomerRepository(session).create(
                    name=name, phone=unique("13800")
                )
                customer_id = str(customer.id)
        finally:
            await database.dispose()
        cleaner("customers", "id", customer_id)
        return {"id": customer_id}

    return factory


@pytest.fixture
def make_house(cleaner):
    async def factory(*, customer_id: str, address: str | None = None) -> dict[str, str]:
        database = Database.from_settings(get_settings())
        house_id = None
        try:
            async with database.session() as session:
                house = await HouseRepository(session).create(
                    customer_id=customer_id,  # type: ignore[arg-type]
                    address=address or f"测试地址 {unique('addr')}",
                    city="上海",
                    area_sqm=Decimal("100.00"),
                    layout="三室两厅",
                )
                house_id = str(house.id)
        finally:
            await database.dispose()
        cleaner("houses", "id", house_id)
        return {"id": house_id}

    return factory


@pytest.fixture
def make_project(cleaner, make_customer, make_house):
    async def factory(
        *, owner_id: str, code: str | None = None, name: str = "集成项目"
    ) -> dict[str, str]:
        customer = await make_customer()
        house = await make_house(customer_id=customer["id"])
        project_code = code or unique("GC")
        database = Database.from_settings(get_settings())
        project_id = None
        try:
            async with database.session() as session:
                projects = ProjectRepository(session)
                project = await projects.create(
                    code=project_code,
                    name=name,
                    customer_id=customer["id"],  # type: ignore[arg-type]
                    house_id=house["id"],  # type: ignore[arg-type]
                )
                await projects.add_member(
                    project_id=project.id,
                    user_id=owner_id,  # type: ignore[arg-type]
                    role=ProjectRole.OWNER,
                )
                project_id = str(project.id)
        finally:
            await database.dispose()
        cleaner("project_members", "project_id", project_id)
        cleaner("projects", "id", project_id)
        return {"id": project_id, "code": project_code}

    return factory


@pytest.fixture
def make_high_risk_skill(cleaner):
    """创建一个 L2 风险的技能（用于验证审批门控）。

    注意：它只有注册中心元数据、没有执行体 —— 因为高风险技能在审批通过前
    根本不会执行，测试也不需要它真的跑起来。
    """

    async def factory(
        *, agent_id: str, skill_id: str, risk: RiskLevel = RiskLevel.L2
    ) -> dict[str, str]:
        database = Database.from_settings(get_settings())
        row_ids: dict[str, str] = {}
        try:
            async with database.session() as session:
                registry = RegistryRepository(session)
                await registry.ensure_skill(
                    skill_id=skill_id,
                    agent_type=AgentType.SUPERVISOR.value,
                    version="0.1.0",
                    required_scopes=["project:read"],
                    risk_level=risk,
                    allowed_tools=[],
                )
                await registry.ensure_agent(
                    agent_id=agent_id,
                    agent_type=AgentType.SUPERVISOR.value,
                    description="高风险测试 Agent",
                    version="0.1.0",
                    supported_skills=[skill_id],
                    required_scopes=["project:read"],
                )
                skill = await registry.get_skill(skill_id)
                agent = await registry.get_agent(agent_id)
                row_ids = {"skill": str(skill.id), "agent": str(agent.id)}
        finally:
            await database.dispose()

        cleaner("skills", "id", row_ids["skill"])
        cleaner("agents", "id", row_ids["agent"])
        # 对外返回的是注册中心里的业务标识（agent_id / skill_id），不是行 UUID
        return {"agent": agent_id, "skill": skill_id}

    return factory


@pytest.fixture
def auth_headers(client, make_user):
    async def factory(
        *, role: RoleName = RoleName.PROJECT_MANAGER, **user_kwargs
    ) -> dict[str, str]:
        user = await make_user(role=role, **user_kwargs)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": user["email"], "password": user["password"]},
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {
            "Authorization": f"Bearer {token}",
            "user": user["id"],
            "email": user["email"],
            "password": user["password"],
        }

    return factory
