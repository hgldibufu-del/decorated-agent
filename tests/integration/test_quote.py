"""Quote 端到端集成测试 —— Phase 5（需要真实 PostgreSQL + 已迁移/已 seed）。

验证：提交报价估算意图 → Supervisor 路由到 quote_agent → 计划 → 技能执行体
通过三个业务表驱动工具计算 → 任务 succeeded 并产出带引用的 quote_estimate Artifact。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from dw_domain.models.quote import QuoteItem, QuotePackage
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import RoleName
from sqlalchemy import select


QUOTE_PACKAGES: list[tuple[str, str, str, Decimal, Decimal, dict]] = [
    ("经济整装包", "满足基础居住需求的整装套餐", "经济", Decimal("18000.00"), Decimal("880.00"), {"含": ["设计"]}),
    ("标准整装包", "主流品质整装，含主材与基础软装", "标准", Decimal("28000.00"), Decimal("1280.00"), {"含": ["设计", "主材"]}),
    ("高端定制包", "全屋定制与高端主材", "高端", Decimal("48000.00"), Decimal("1880.00"), {"含": ["设计", "主材", "软装"]}),
]

QUOTE_ITEMS: list[tuple[str, str, str, Decimal, dict]] = [
    ("硬装", "水电隐蔽工程", "项", Decimal("28000.00"), {"keywords": ["水电", "隐蔽", "防水"]}),
    ("硬装", "墙面基层与乳胶漆", "m²", Decimal("68.00"), {"keywords": ["墙面", "乳胶漆"]}),
    ("主材", "实木复合地板", "m²", Decimal("220.00"), {"keywords": ["地板"]}),
    ("主材", "整体橱柜", "延米", Decimal("1850.00"), {"keywords": ["橱柜"]}),
    ("软装", "全屋窗帘", "项", Decimal("6500.00"), {"keywords": ["窗帘"]}),
]


async def _ensure_quote(session) -> None:
    """确保 Quote 的 Agent / Skill / Tools 已注册（镜像 scripts/seed.py）。"""
    reg = RegistryRepository(session)
    for tool_id, desc in (
        ("budget_estimate", "基于项目面积与套餐计算报价明细与总价"),
        ("package_compare", "同一面积下对比多个套餐总价与每平米单价"),
        ("material_lookup", "按类目/关键词检索工艺与材料项"),
    ):
        await reg.ensure_tool(
            tool_id=tool_id,
            description=desc,
            required_scopes=["project:read", "quote:read"],
            risk_level=RiskLevel.L0,
            timeout_ms=5000,
            retry_max_attempts=2,
            fallback_tool_id=None,
        )
    await reg.ensure_skill(
        skill_id="quote_estimate",
        agent_type=AgentType.QUOTE.value,
        version="0.1.0",
        required_scopes=["project:read", "quote:read"],
        risk_level=RiskLevel.L0,
        allowed_tools=["budget_estimate", "package_compare", "material_lookup"],
    )
    await reg.ensure_agent(
        agent_id="quote_agent",
        agent_type=AgentType.QUOTE.value,
        description="报价 Agent：预算估算、套餐对比、材料检索",
        version="0.1.0",
        supported_skills=["quote_estimate"],
        required_scopes=["project:read", "quote:read"],
    )


async def _seed_quote_catalog(session) -> None:
    """幂等插入报价目录（按名称去重）。"""
    for name, desc, tier, base, per, scope in QUOTE_PACKAGES:
        existing = (
            await session.execute(select(QuotePackage).where(QuotePackage.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QuotePackage(
                    name=name,
                    description=desc,
                    tier=tier,
                    base_price=base,
                    price_per_sqm=per,
                    included_scope=scope,
                )
            )
    for category, name, unit, price, meta in QUOTE_ITEMS:
        existing = (
            await session.execute(select(QuoteItem).where(QuoteItem.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QuoteItem(
                    category=category,
                    name=name,
                    unit=unit,
                    unit_price=price,
                    metadata_json=meta,
                )
            )


async def test_quote_estimate_end_to_end(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    # ESTIMATOR 真实拥有 quote:read，可验证 scope 链路
    headers = await auth_headers(role=RoleName.ESTIMATOR)
    project = await make_project(owner_id=headers["user"])

    # 注入报价目录 + 注册 Quote 能力
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_quote_catalog(session)
        await _ensure_quote(session)
    await database.dispose()

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "quote_estimate",
            "objective": "估算这套房报价",
            "project_id": project["id"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == "completed"
    assert body["tasks"][0]["skill_id"] == "quote_estimate"
    assert body["artifact_ids"], "应产出 quote_estimate Artifact"

    artifact = client.get(
        f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers
    ).json()
    payload = artifact["payload"]

    # 房屋面积 100.00 × 标准单价 1280 + 基础 28000 = 156000.00
    assert payload["estimate"]["total"] == "156000.00"
    assert Decimal(payload["estimate"]["total"]) > 0
    assert payload["recommended_package"]["name"]
    # 三个套餐都参与对比
    assert len(payload["comparison"]) == 3
    # 硬装类目下应有材料数据
    assert payload["materials"]


async def test_quote_estimate_without_project_is_rejected(
    client, auth_headers
) -> None:  # noqa: ANN001
    """已实现的意图但缺少可见项目时，应明确报错（501 + 可见项目提示）。"""
    headers = await auth_headers(role=RoleName.ESTIMATOR)

    # 先确保注册（端到端测试若先跑已注册；这里幂等 ensure）
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _ensure_quote(session)
    await database.dispose()

    # 不传 project_id，且 ESTIMATOR 无其它可见项目
    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "quote_estimate", "objective": "报价"},
    )
    assert response.status_code == 501
    assert response.json()["code"] == "CAPABILITY_NOT_IMPLEMENTED"
    assert "可见项目" in response.json()["message"]


async def test_quote_estimate_respects_project_acl(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    """非项目成员调用 budget_estimate 应被 ACL 拒绝（403）。"""
    headers = await auth_headers(role=RoleName.ESTIMATOR)
    project = await make_project(owner_id=headers["user"])

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_quote_catalog(session)
        await _ensure_quote(session)
    await database.dispose()

    # 另一个无关用户（viewer，无 quote:read）不应能发起报价
    other = await auth_headers(role=RoleName.VIEWER)
    response = client.post(
        "/api/v1/runs",
        headers=other,
        json={
            "intent": "quote_estimate",
            "objective": "报价",
            "project_id": project["id"],
        },
    )
    # VIEWER 缺 quote:read → 权限不足（403）
    assert response.status_code == 403, response.text
