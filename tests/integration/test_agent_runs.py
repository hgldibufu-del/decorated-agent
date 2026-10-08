"""Agent Run / Artifact / Approval 端到端（HTTP → RunService → 真实 PostgreSQL）。"""

from __future__ import annotations

from uuid import uuid4

from dw_schemas.agent import ApprovalStatus, RunStatus, TaskStatus
from dw_schemas.iam import RoleName

SUPERVISOR = "supervisor_agent"
SNAPSHOT = "project_snapshot"


def run_payload(project_id: str | None = None, **overrides) -> dict:
    """第一个位置参数同时填 `project_id` 与技能入参里的 project_id。"""
    base = {
        "agent_id": SUPERVISOR,
        "skill_id": SNAPSHOT,
        "objective": "加载项目上下文",
        "project_id": project_id,
        "input": {"project_id": project_id} if project_id else {},
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
# 注册中心
# -----------------------------------------------------------------------------
async def test_registry_endpoints_expose_seeded_entries(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    agents = client.get("/api/v1/agents", headers=headers)
    assert agents.status_code == 200
    assert any(item["agent_id"] == SUPERVISOR for item in agents.json())

    skills = client.get("/api/v1/skills", headers=headers)
    assert skills.status_code == 200
    snapshot = next(item for item in skills.json() if item["skill_id"] == SNAPSHOT)
    assert "project_query" in snapshot["allowed_tools"]

    tools = client.get("/api/v1/tools", headers=headers)
    assert tools.status_code == 200
    assert {"project_query", "project_list", "artifact_query"} <= {
        item["tool_id"] for item in tools.json()
    }


async def test_registry_requires_authentication(client):
    assert client.get("/api/v1/agents").status_code == 401
    assert client.get("/api/v1/skills").status_code == 401
    assert client.get("/api/v1/tools").status_code == 401


# -----------------------------------------------------------------------------
# Run：Direct 模式
# -----------------------------------------------------------------------------
async def test_run_produces_artifact_and_records_tool_call(
    client, auth_headers, make_project, cleaner
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])

    created = client.post("/api/v1/runs", headers=headers, json=run_payload(project["id"]))
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == RunStatus.COMPLETED.value
    assert body["tasks"][0]["skill_id"] == SNAPSHOT
    assert body["tasks"][0]["status"] == TaskStatus.COMPLETED.value
    assert len(body["artifact_ids"]) == 1

    artifact = client.get(f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers)
    assert artifact.status_code == 200
    assert artifact.json()["payload"]["project"]["code"] == project["code"]
    assert artifact.json()["artifact_type"] == "project_snapshot"

    calls = client.get(f"/api/v1/runs/{body['id']}/tool-calls", headers=headers)
    assert calls.status_code == 200
    # Phase 10 起：有 memory:read 的用户在快照阶段会顺带召回长期记忆（§35 context loading）
    assert [call["tool_id"] for call in calls.json()] == ["project_query", "memory_recall"]
    assert all(call["status"] == "success" for call in calls.json())

    events = client.get(f"/api/v1/runs/{body['id']}/events", headers=headers)
    assert {event["kind"] for event in events.json()} >= {"run", "task", "tool_call"}


async def test_run_detail_is_readable_by_owner(client, auth_headers, make_project, cleaner):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])
    created = client.post("/api/v1/runs", headers=headers, json=run_payload(project["id"]))
    run_id = created.json()["id"]
    cleaner("agent_runs", "id", run_id)

    detail = client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id


async def test_run_of_another_users_project_is_denied(
    client, auth_headers, make_project, make_user
):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    designer = await auth_headers(role=RoleName.DESIGNER)
    response = client.post("/api/v1/runs", headers=designer, json=run_payload(project["id"]))

    assert response.status_code == 403
    # 这是工具层的拒绝（project_query 内部过 Project ACL），因此是 TOOL_PERMISSION_DENIED
    assert response.json()["code"] == "TOOL_PERMISSION_DENIED"


async def test_run_visibility_is_scoped_to_requester(client, auth_headers, make_project, cleaner):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])
    created = client.post("/api/v1/runs", headers=owner, json=run_payload(project["id"]))
    run_id = created.json()["id"]
    cleaner("agent_runs", "id", run_id)

    stranger = await auth_headers(role=RoleName.DESIGNER)
    assert client.get(f"/api/v1/runs/{run_id}", headers=stranger).status_code == 403


async def test_unknown_skill_returns_404(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.post("/api/v1/runs", headers=headers, json=run_payload(skill_id="nope"))

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_skill_outside_agent_allowlist_is_rejected(
    client, auth_headers, make_high_risk_skill, cleaner
):
    """Agent 不支持该 Skill 时应在规划阶段被拦下（400），而不是执行到一半才失败。"""
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    entries = await make_high_risk_skill(
        agent_id=f"picky_agent_{uuid4().hex[:8]}", skill_id=f"picky_skill_{uuid4().hex[:8]}"
    )

    response = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "agent_id": entries["agent"],
            "skill_id": SNAPSHOT,  # 已注册，但不在该 Agent 的支持列表里
            "objective": "越权组合",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


# -----------------------------------------------------------------------------
# 审批门控（§15）
# -----------------------------------------------------------------------------
async def test_high_risk_skill_waits_for_approval(
    client, auth_headers, make_high_risk_skill, cleaner
):
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
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == RunStatus.AWAITING_APPROVAL.value
    assert body["approval_id"] is not None
    # 关键：审批前不得产生任何 Artifact
    assert body["artifact_ids"] == []


async def test_approve_then_reject_different_runs(
    client, auth_headers, make_high_risk_skill, cleaner
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    entries = await make_high_risk_skill(
        agent_id=f"risky_agent_{uuid4().hex[:8]}", skill_id=f"risky_skill_{uuid4().hex[:8]}"
    )

    def new_run() -> dict:
        response = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "agent_id": entries["agent"],
                "skill_id": entries["skill"],
                "objective": "高风险操作",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        cleaner("agent_runs", "id", body["id"])
        return body

    approved_run = new_run()
    approved = client.post(
        f"/api/v1/approvals/{approved_run['approval_id']}/approve",
        headers=headers,
        json={"decision": "approve", "comment": "同意"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == ApprovalStatus.APPROVED.value

    rejected_run = new_run()
    rejected = client.post(
        f"/api/v1/approvals/{rejected_run['approval_id']}/reject",
        headers=headers,
        json={"decision": "reject", "comment": "预算不符"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == ApprovalStatus.REJECTED.value

    # 拒绝是终态决策：Run 必须立刻失败，不能继续挂着
    detail = client.get(f"/api/v1/runs/{rejected_run['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == RunStatus.FAILED.value


async def test_approval_requires_write_scope(client, auth_headers, make_high_risk_skill, cleaner):
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

    # 预算员有 project:read/quotes，但没有 project:write → 不能审批
    estimator = await auth_headers(role=RoleName.ESTIMATOR)
    response = client.post(
        f"/api/v1/approvals/{run['approval_id']}/approve",
        headers=estimator,
        json={"decision": "approve"},
    )
    assert response.status_code == 403


async def test_unknown_approval_returns_404(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    response = client.post(
        f"/api/v1/approvals/{uuid4()}/approve", headers=headers, json={"decision": "approve"}
    )
    assert response.status_code == 404
