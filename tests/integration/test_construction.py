"""Construction 端到端集成测试 —— Phase 7（需要真实 PostgreSQL + 已迁移/已 seed）。

验证：提交施工审查意图 → Supervisor 路由到 construction_agent → 计划 → 技能执行体
通过两个业务表驱动工具分析 → 任务 succeeded 并产出带引用的 construction_review Artifact。
"""

from __future__ import annotations

from uuid import UUID

from dw_domain.models.construction import ConstructionMilestone, QualityChecklist
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import RoleName
from sqlalchemy import select


# (stage, seq, planned_days, actual_days, status)
CONSTRUCTION_MILESTONES: list[tuple[str, int, int, int | None, str]] = [
    ("水电改造", 1, 7, 7, "completed"),
    ("泥瓦工程", 2, 10, 13, "completed"),
    ("木工工程", 3, 8, None, "in_progress"),
    ("油漆工程", 4, 6, None, "pending"),
]

QUALITY_ITEMS: list[tuple[str, str, str, int, str]] = [
    ("水电", "强弱电分离", "强弱电间距≥300mm，交叉处屏蔽", 3, "高"),
    ("防水", "闭水试验", "蓄水 24h 无渗漏", 3, "高"),
]


async def _ensure_construction(session) -> None:
    """确保 Construction 的 Agent / Skill / Tools 已注册（镜像 scripts/seed.py）。"""
    reg = RegistryRepository(session)
    for tool_id, desc in (
        ("progress_analysis", "按项目施工阶段对比计划 / 实际工期"),
        ("quality_check", "按类目评估验收项并给出加权得分"),
    ):
        await reg.ensure_tool(
            tool_id=tool_id,
            description=desc,
            required_scopes=["project:read", "construction:read"],
            risk_level=RiskLevel.L0,
            timeout_ms=5000,
            retry_max_attempts=2,
            fallback_tool_id=None,
        )
    await reg.ensure_skill(
        skill_id="construction_review",
        agent_type=AgentType.CONSTRUCTION.value,
        version="0.1.0",
        required_scopes=["project:read", "construction:read"],
        risk_level=RiskLevel.L0,
        allowed_tools=["progress_analysis", "quality_check"],
    )
    await reg.ensure_agent(
        agent_id="construction_agent",
        agent_type=AgentType.CONSTRUCTION.value,
        description="施工 Agent：进度分析、验收评估、施工审查",
        version="0.1.0",
        supported_skills=["construction_review"],
        required_scopes=["project:read", "construction:read"],
    )


async def _seed_milestones(session, project_id: str) -> None:
    """为测试项目写入施工阶段（幂等，按 stage 去重）。"""
    pid = UUID(project_id)
    for stage, seq, planned, actual, status in CONSTRUCTION_MILESTONES:
        existing = (
            await session.execute(
                select(ConstructionMilestone).where(
                    ConstructionMilestone.project_id == pid,
                    ConstructionMilestone.stage == stage,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ConstructionMilestone(
                    project_id=pid,
                    stage=stage,
                    seq=seq,
                    planned_days=planned,
                    actual_days=actual,
                    status=status,
                )
            )


async def _seed_quality(session) -> None:
    for category, item, standard, weight, severity in QUALITY_ITEMS:
        existing = (
            await session.execute(select(QualityChecklist).where(QualityChecklist.item == item))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QualityChecklist(
                    category=category,
                    item=item,
                    standard=standard,
                    weight=weight,
                    severity=severity,
                )
            )


async def test_construction_review_end_to_end(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    # CONSTRUCTION_MANAGER 真实拥有 construction:read，可验证 scope + ACL 链路
    headers = await auth_headers(role=RoleName.CONSTRUCTION_MANAGER)
    project = await make_project(owner_id=headers["user"])

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_milestones(session, project["id"])
        await _seed_quality(session)
        await _ensure_construction(session)
    await database.dispose()

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "construction_review",
            "objective": "审一下施工进度",
            "project_id": project["id"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == "completed"
    assert body["tasks"][0]["skill_id"] == "construction_review"
    assert body["artifact_ids"], "应产出 construction_review Artifact"

    artifact = client.get(
        f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers
    ).json()
    payload = artifact["payload"]

    # 计划合计 7+10+8+6=31；已完成实际 7+13=20；泥瓦延期 3 天 → at_risk
    assert payload["progress"]["total_planned_days"] == 31
    assert payload["progress"]["total_actual_days"] == 20
    assert payload["progress"]["progress_ratio"] == 0.5
    assert payload["progress"]["at_risk"] is True
    assert payload["progress"]["delayed_stages"][0]["stage"] == "泥瓦工程"
    assert payload["quality"]["score"] == 1.0
    assert payload["quality"]["passed"] is True
    assert payload["suggestions"]
    assert payload["confidence"] == 0.82


async def test_construction_review_without_project_is_rejected(
    client, auth_headers
) -> None:  # noqa: ANN001
    """已实现的意图但缺少可见项目时，应明确报错（501 + 可见项目提示）。"""
    headers = await auth_headers(role=RoleName.CONSTRUCTION_MANAGER)

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _ensure_construction(session)
    await database.dispose()

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "construction_review", "objective": "施工"},
    )
    assert response.status_code == 501
    assert response.json()["code"] == "CAPABILITY_NOT_IMPLEMENTED"
    assert "可见项目" in response.json()["message"]


async def test_construction_review_respects_scope(
    client, auth_headers, make_project
) -> None:  # noqa: ANN001
    """缺 construction:read 且非项目成员（VIEWER）不应能发起施工审查（403）。"""
    headers = await auth_headers(role=RoleName.CONSTRUCTION_MANAGER)
    project = await make_project(owner_id=headers["user"])

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_milestones(session, project["id"])
        await _ensure_construction(session)
    await database.dispose()

    other = await auth_headers(role=RoleName.VIEWER)
    response = client.post(
        "/api/v1/runs",
        headers=other,
        json={
            "intent": "construction_review",
            "objective": "施工",
            "project_id": project["id"],
        },
    )
    # VIEWER 缺 construction:read → 权限不足（403）
    assert response.status_code == 403, response.text
