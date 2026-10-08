"""记忆层集成测试 —— Phase 10（需要真实 PostgreSQL + 已迁移 + 已 seed）。

覆盖：

1. REST 往返：写 → 列 → **幂等更新**（不产生第二条）→ 删；
2. 缺 `memory:read` / `memory:write` → 403；
3. Run 完成后**自动抽取**落库（受 `memory:write` 约束，`source` 可追溯）；
4. 记忆被**真正消费**：`design_proposal` 未显式给偏好时回落长期记忆；
5. 反向保护：无权读记忆的用户（VIEWER）跑 supervisor 路径**不会**因记忆工具失败。
"""

from __future__ import annotations

from dw_domain.models.design import DesignStyle
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import ProjectRole, RoleName
from sqlalchemy import select


async def _ensure_design(session) -> None:  # noqa: ANN001
    """确保 Design 的 Agent / Skill / Tools 已注册（镜像 scripts/seed.py）。"""
    registry = RegistryRepository(session)
    for tool_id, description in (
        ("layout_analysis", "基于项目户型与面积产出空间规划建议"),
        ("style_match", "按偏好 / 约束匹配并排序设计风格"),
    ):
        await registry.ensure_tool(
            tool_id=tool_id,
            description=description,
            required_scopes=["project:read", "design:read"],
            risk_level=RiskLevel.L0,
            timeout_ms=5000,
            retry_max_attempts=2,
            fallback_tool_id=None,
        )
    await registry.ensure_skill(
        skill_id="design_proposal",
        agent_type=AgentType.DESIGN.value,
        version="0.1.0",
        required_scopes=["project:read", "design:read"],
        risk_level=RiskLevel.L0,
        allowed_tools=["layout_analysis", "style_match"],
    )
    await registry.ensure_agent(
        agent_id="design_agent",
        agent_type=AgentType.DESIGN.value,
        description="设计 Agent：空间规划、风格匹配、设计提案",
        version="0.1.0",
        supported_skills=["design_proposal"],
        required_scopes=["project:read", "design:read"],
    )


async def _ensure_styles(session) -> None:  # noqa: ANN001
    """幂等插入两个风格（够验证「偏好决定首位」即可）。"""
    for name, tags in (("现代简约", ["现代", "简约"]), ("新中式", ["传统", "沉稳"])):
        existing = (
            await session.execute(select(DesignStyle).where(DesignStyle.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DesignStyle(
                    name=name,
                    style_family=name,
                    description=f"{name}风格说明",
                    suitable_layouts=["三室两厅"],
                    palette=["#FFFFFF"],
                    characteristics={},
                    tags=tags,
                )
            )


async def test_memory_api_roundtrip_is_idempotent(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.DESIGNER)
    payload = {"kind": "preference", "key": "style", "value": "北欧"}

    first = client.post("/api/v1/memories", headers=headers, json=payload)
    assert first.status_code == 200, first.text

    # 同 (kind, key) 再写一次 → 更新同一条，而不是新增
    second = client.post(
        "/api/v1/memories", headers=headers, json={**payload, "value": "新中式"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    listed = client.get("/api/v1/memories", headers=headers).json()
    assert [item["key"] for item in listed] == ["style"]
    assert listed[0]["value"] == "新中式"
    assert listed[0]["source"] == "manual"

    deleted = client.delete("/api/v1/memories/style", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1
    assert client.get("/api/v1/memories", headers=headers).json() == []


async def test_memory_requires_scope(client, auth_headers) -> None:  # noqa: ANN001
    """VIEWER 只有 project:read → 记忆读写都应被拒。"""
    viewer = await auth_headers(role=RoleName.VIEWER)

    assert client.get("/api/v1/memories", headers=viewer).status_code == 403
    assert (
        client.post(
            "/api/v1/memories",
            headers=viewer,
            json={"kind": "preference", "key": "style", "value": "北欧"},
        ).status_code
        == 403
    )
    assert client.delete("/api/v1/memories/style", headers=viewer).status_code == 403


async def test_memory_tools_are_registered_and_governed(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    tools = {item["tool_id"] for item in client.get("/api/v1/tools", headers=headers).json()}
    assert {"memory_recall", "memory_remember"} <= tools

    skills = {
        item["skill_id"]: item for item in client.get("/api/v1/skills", headers=headers).json()
    }
    assert "memory_recall" in skills["project_snapshot"]["allowed_tools"]
    # 但不得进入 required_scopes —— 否则只读用户会被「可选个性化」挡住
    assert "memory:read" not in skills["project_snapshot"]["required_scopes"]


async def test_run_learns_preferences_automatically(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=headers["user"])

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "project_overview",
            "objective": "客户预算有限，喜欢北欧，重视收纳",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])
    assert body["status"] == "completed"

    # 快照阶段顺带召回记忆（受治理的工具调用，出现在 Run 时间线上）
    calls = client.get(f"/api/v1/runs/{body['id']}/tool-calls", headers=headers).json()
    assert "memory_recall" in [call["tool_id"] for call in calls]

    memories = {
        item["key"]: item
        for item in client.get("/api/v1/memories", headers=headers).json()
    }
    assert memories["style"]["value"] == "北欧"
    assert memories["budget.sensitivity"]["value"] == "high"
    assert memories["focus.storage"]["value"] is True
    # 来源可追溯：知道自己为什么「记得」
    assert memories["style"]["source"].startswith("run:")


async def test_memory_is_consumed_by_design_proposal(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    """同一句「再出一套设计方案」，第二次应复用第一次学到的风格偏好。"""
    headers = await auth_headers(role=RoleName.DESIGNER)
    project = await make_project(owner_id=headers["user"])

    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _ensure_design(session)
        await _ensure_styles(session)
    await database.dispose()

    # 第一次：objective 显式提到风格 → Run 完成后被自动抽取进长期记忆
    first = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "design_proposal",
            "objective": "客户喜欢新中式",
            "project_id": project["id"],
        },
    )
    assert first.status_code == 201, first.text
    cleaner("agent_runs", "id", first.json()["id"])
    assert first.json()["status"] == "completed"

    memorized = {
        item["key"]: item["value"]
        for item in client.get("/api/v1/memories", headers=headers).json()
    }
    assert memorized["style"] == "新中式"

    # 第二次：objective 不再提风格 → 回落长期记忆，产出必须体现出来
    second = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "intent": "design_proposal",
            "objective": "再出一套设计方案",
            "project_id": project["id"],
        },
    )
    assert second.status_code == 201, second.text
    body = second.json()
    cleaner("agent_runs", "id", body["id"])

    artifact = client.get(f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers).json()
    payload = artifact["payload"]
    assert payload["memory_preference"] == "新中式"
    assert payload["preference_used"] == "新中式"
    assert payload["recommended_styles"][0]["name"] == "新中式"
    # provenance：产物明确标注偏好来自记忆而非本次请求
    assert any("长期记忆" in note for note in payload["assumptions"])


async def test_supervisor_run_survives_for_user_without_memory_scope(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    """反向保护：缺 memory:read 的用户不应因为「可选个性化」而 Run 失败。"""
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    viewer = await auth_headers(role=RoleName.VIEWER)
    added = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": viewer["user"], "role": ProjectRole.VIEWER.value},
    )
    assert added.status_code == 200, added.text

    created = client.post(
        "/api/v1/runs",
        headers=viewer,
        json={"intent": "project_overview", "objective": "看一眼项目"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == "completed"
    # 无 memory:read → 根本不调用记忆工具（而不是调用后被拒导致整次 Run 失败）
    calls = client.get(f"/api/v1/runs/{body['id']}/tool-calls", headers=viewer).json()
    assert [call["tool_id"] for call in calls] == ["project_query"]
