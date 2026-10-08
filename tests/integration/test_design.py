"""Design 端到端集成测试 —— Phase 6（需要真实 PostgreSQL + 已迁移/已 seed）。

验证：提交设计提案意图 → Supervisor 路由到 design_agent → 计划 → 技能执行体
通过两个业务表驱动工具检索 → 任务 succeeded 并产出带引用的 design_proposal Artifact。
"""

from __future__ import annotations

from dw_domain.models.design import DesignStyle, LayoutModule
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import RoleName
from sqlalchemy import select


DESIGN_STYLES: list[tuple[str, str, str, list[str], list[str], dict, list[str]]] = [
    ("现代简约", "现代简约", "强调留白与功能性", ["三室两厅"], ["#F5F5F5", "#222222"], {"明亮通透": True}, ["现代", "简约"]),
    ("新中式", "新中式", "东方美学重构空间", ["三室两厅"], ["#8C6A4F"], {"文化底蕴": True}, ["传统", "沉稳"]),
]
LAYOUT_MODULES: list[tuple[str, str, str, str, str]] = [
    ("卧室", "休息与收纳", "静谧色调", "主材", ""),
    ("客厅", "会客与家庭活动", "开阔通透", "主材", ""),
    ("餐厅", "用餐", "灯光温馨", "软装", ""),
    ("厨房", "烹饪", "易清洁", "硬装", ""),
    ("卫生间", "洗漱沐浴", "防水优先", "硬装", ""),
    ("阳台", "休闲 / 晾晒", "兼顾采光", "主材", ""),
]


async def _ensure_design(session) -> None:
    """确保 Design 的 Agent / Skill / Tools 已注册（镜像 scripts/seed.py）。"""
    reg = RegistryRepository(session)
    for tool_id, desc in (
        ("layout_analysis", "基于项目户型与面积产出空间规划建议"),
        ("style_match", "按偏好 / 约束匹配并排序设计风格"),
    ):
        await reg.ensure_tool(
            tool_id=tool_id,
            description=desc,
            required_scopes=["project:read", "design:read"],
            risk_level=RiskLevel.L0,
            timeout_ms=5000,
            retry_max_attempts=2,
            fallback_tool_id=None,
        )
    await reg.ensure_skill(
        skill_id="design_proposal",
        agent_type=AgentType.DESIGN.value,
        version="0.1.0",
        required_scopes=["project:read", "design:read"],
        risk_level=RiskLevel.L0,
        allowed_tools=["layout_analysis", "style_match"],
    )
    await reg.ensure_agent(
        agent_id="design_agent",
        agent_type=AgentType.DESIGN.value,
        description="设计 Agent：空间规划、风格匹配、设计提案",
        version="0.1.0",
        supported_skills=["design_proposal"],
        required_scopes=["project:read", "design:read"],
    )


async def _seed_design_catalog(session) -> None:
    """幂等插入设计目录（按名称去重）。"""
    for name, family, desc, layouts, palette, chars, tags in DESIGN_STYLES:
        existing = (
            await session.execute(select(DesignStyle).where(DesignStyle.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DesignStyle(
                    name=name,
                    style_family=family,
                    description=desc,
                    suitable_layouts=layouts,
                    palette=palette,
                    characteristics=chars,
                    tags=tags,
                )
            )
    for room_type, function, principle, category, notes in LAYOUT_MODULES:
        existing = (
            await session.execute(
                select(LayoutModule).where(LayoutModule.room_type == room_type)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                LayoutModule(
                    room_type=room_type,
                    suggested_function=function,
                    design_principle=principle,
                    recommended_material_category=category,
                    notes=notes,
                )
            )


async def test_design_proposal_end_to_end(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    # DESIGNER 真实拥有 design:read，可验证 scope + ACL 链路
    headers = await auth_headers(role=RoleName.DESIGNER)
    project = await make_project(owner_id=headers["user"])

    # 注入设计目录 + 注册 Design 能力
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_design_catalog(session)
        await _ensure_design(session)
    await database.dispose()

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "design_proposal",
            "objective": "出一套现代简约设计方案",
            "project_id": project["id"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == "completed"
    assert body["tasks"][0]["skill_id"] == "design_proposal"
    assert body["artifact_ids"], "应产出 design_proposal Artifact"

    artifact = client.get(
        f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers
    ).json()
    payload = artifact["payload"]

    # make_project 的房屋：面积 100.00 m²，户型 三室两厅
    assert payload["layout"] == "三室两厅"
    assert payload["area_sqm"] == "100.00"
    # 卧室/客厅/餐厅/厨房/卫生间/阳台 都应被空间建议覆盖
    assert len(payload["space_planning"]) >= 5
    assert payload["recommended_styles"]
    assert payload["recommended_palette"]
    assert payload["suggested_material_categories"]
    assert payload["confidence"] == 0.8


async def test_design_proposal_without_project_is_rejected(
    client, auth_headers
) -> None:  # noqa: ANN001
    """已实现的意图但缺少可见项目时，应明确报错（501 + 可见项目提示）。"""
    headers = await auth_headers(role=RoleName.DESIGNER)

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _ensure_design(session)
    await database.dispose()

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "design_proposal", "objective": "设计"},
    )
    assert response.status_code == 501
    assert response.json()["code"] == "CAPABILITY_NOT_IMPLEMENTED"
    assert "可见项目" in response.json()["message"]


async def test_design_proposal_respects_scope(
    client, auth_headers, make_project
) -> None:  # noqa: ANN001
    """缺 design:read 且非项目成员（VIEWER）不应能发起设计提案（403）。"""
    headers = await auth_headers(role=RoleName.DESIGNER)
    project = await make_project(owner_id=headers["user"])

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_design_catalog(session)
        await _ensure_design(session)
    await database.dispose()

    other = await auth_headers(role=RoleName.VIEWER)
    response = client.post(
        "/api/v1/runs",
        headers=other,
        json={
            "intent": "design_proposal",
            "objective": "设计",
            "project_id": project["id"],
        },
    )
    # VIEWER 缺 design:read → 权限不足（403）
    assert response.status_code == 403, response.text
