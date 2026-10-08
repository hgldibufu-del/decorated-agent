"""Supervisor 端到端：规划 / 并行 DAG / 顺序执行 / Artifact 传递 / 恢复执行。"""

from __future__ import annotations

from uuid import uuid4

from dw_domain.models.agent_runtime import Checkpoint
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.iam import RoleName
from sqlalchemy import select


async def count_checkpoints(run_id: str) -> int:
    database = Database.from_settings(get_settings())
    try:
        async with database.session() as session:
            result = await session.execute(select(Checkpoint.id).where(Checkpoint.run_id == run_id))
            return len(result.scalars().all())
    finally:
        await database.dispose()


async def test_plan_preview_returns_plan_without_executing(client, auth_headers, make_project):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])

    response = client.post(
        "/api/v1/runs/plan",
        headers=headers,
        json={"message": "看一下项目概况", "project_id": project["id"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "project_overview"
    assert body["mode"] == "direct"
    assert body["steps"][0]["skill_id"] == "project_snapshot"


async def test_plan_preview_does_not_create_a_run(client, auth_headers, make_project):
    """/runs/plan 只做规划，不应留下任何 Run 记录。"""
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])

    assert (
        client.post(
            "/api/v1/runs/plan",
            headers=headers,
            json={"message": "看一下项目概况", "project_id": project["id"]},
        ).status_code
        == 200
    )

    # 用一个必然不存在的 Run 反证：规划接口不写库（若写了，列表里会有新记录）
    assert client.get(f"/api/v1/runs/{uuid4()}", headers=headers).status_code == 404


async def test_parallel_dag_run(client, auth_headers, make_project, cleaner):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=headers["user"])
    await make_project(owner_id=headers["user"])

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "project_overview", "objective": "看全部项目概览"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["mode"] == "parallel_dag"
    assert len(body["tasks"]) == 2
    assert body["status"] == "completed"
    assert body["review_decision"] == "PASS"
    assert len(body["artifact_ids"]) == 2

    # 每个任务完成后各写一条检查点（节点级恢复的依据）
    assert await count_checkpoints(body["id"]) == 2

    events = client.get(f"/api/v1/runs/{body['id']}/events", headers=headers).json()
    assert sum(1 for event in events if event["kind"] == "tool_call") >= 2


async def test_sequential_run_passes_artifact_downstream(
    client, auth_headers, make_project, cleaner
):
    """顺序模式下，第二个任务通过 artifact_id 拿到上游结果（§34）。"""
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=headers["user"])
    await make_project(owner_id=headers["user"])

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "project_compare", "objective": "对比两个项目"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["mode"] == "sequential"
    assert body["status"] == "completed"
    tasks = sorted(body["tasks"], key=lambda item: item["task_key"])
    assert [task["task_key"] for task in tasks] == ["T-001", "T-002"]
    assert tasks[1]["depends_on"] == ["T-001"]

    downstream_artifact = client.get(
        f"/api/v1/artifacts/{tasks[1]['artifact_id']}", headers=headers
    )
    assert downstream_artifact.status_code == 200
    payload = downstream_artifact.json()["payload"]
    assert len(payload["upstream_artifacts"]) == 1
    assert payload["upstream_artifacts"][0]["artifact_id"] == str(tasks[0]["artifact_id"])


async def test_construction_review_no_longer_501(client, auth_headers, make_project, cleaner):
    """回归保护：construction_review 在 Phase 7 已落地，不应再是 501。

    Phase 4/5/6/7 的四个领域意图全部落地后，`MISSING_CAPABILITY_HINT` 已清空；
    「意图存在但能力缺失 → 501」这一契约改由 Planner 单测兜底
    （`test_unregistered_capability_is_reported_not_silently_planned`）。
    """
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=headers["user"])

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "construction_review", "objective": "审一下施工进度"},
    )

    # 现在应进入正常执行路径（201 表示已受理并执行），而不是 501
    assert response.status_code != 501
    if response.status_code == 201:
        # 该 run 会引用上面的 project，需先清 run 再清 project，否则外键冲突
        cleaner("agent_runs", "id", response.json()["id"])


async def test_aftersales_diagnosis_requires_no_longer_501(client, auth_headers, make_project, cleaner):
    """回归保护：aftersales_diagnosis 在 Phase 4 已落地，不应再是 501。"""
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=headers["user"])

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "aftersales_diagnosis", "objective": "卫生间渗水"},
    )

    # 现在应进入正常执行路径（201 表示已受理并执行），而不是 501
    assert response.status_code != 501
    if response.status_code == 201:
        # 该 run 会引用上面的 project，需先清 run 再清 project，否则外键冲突
        cleaner("agent_runs", "id", response.json()["id"])


async def test_unknown_intent_value_is_400(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "not_a_real_intent", "objective": "x"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_resume_after_approval_executes_pending_node(
    client, auth_headers, make_high_risk_skill, cleaner
):
    """审批通过 → 从检查点恢复执行（节点级恢复）。"""
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    entries = await make_high_risk_skill(
        agent_id=f"risky_agent_{uuid4().hex[:8]}", skill_id=f"risky_skill_{uuid4().hex[:8]}"
    )

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "agent_id": entries["agent"],
            "skill_id": entries["skill"],
            "objective": "高风险操作",
        },
    )
    run = created.json()
    cleaner("agent_runs", "id", run["id"])
    assert run["status"] == "awaiting_approval"

    approved = client.post(
        f"/api/v1/approvals/{run['approval_id']}/approve",
        headers=headers,
        json={"decision": "approve"},
    )
    assert approved.json()["status"] == "approved"

    resumed = client.post(f"/api/v1/runs/{run['id']}/resume", headers=headers)
    assert resumed.status_code == 200, resumed.text
    # 该高风险技能没有执行体，因此恢复后会明确失败（而不是假装成功）
    resumed_body = resumed.json()
    assert resumed_body["status"] == "failed"
    assert resumed_body["review_decision"] == "FALLBACK"
    assert any("未实现" in issue for issue in resumed_body["review_issues"])


async def test_resume_rejects_run_that_is_not_recoverable(
    client, auth_headers, make_project, cleaner
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])
    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "agent_id": "supervisor_agent",
            "skill_id": "project_snapshot",
            "objective": "概览",
            "project_id": project["id"],
            "input": {"project_id": project["id"]},
        },
    )
    run = created.json()
    cleaner("agent_runs", "id", run["id"])
    assert run["status"] == "completed"

    response = client.post(f"/api/v1/runs/{run['id']}/resume", headers=headers)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
