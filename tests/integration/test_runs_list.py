"""`GET /runs` 运行历史集成测试：按 requester 收敛 + limit。"""

from __future__ import annotations

from dw_schemas.iam import RoleName


async def test_runs_list_is_scoped_to_requester(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    pm1 = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=pm1["user"])

    created = client.post(
        "/api/v1/runs",
        headers=pm1,
        json={"intent": "project_overview", "objective": "看概览"},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    cleaner("agent_runs", "id", run_id)

    mine = client.get("/api/v1/runs", headers=pm1)
    assert mine.status_code == 200
    assert any(run["id"] == run_id for run in mine.json())

    # 另一个用户不应看到别人的 Run（Run 可能含客户敏感信息）
    pm2 = await auth_headers(role=RoleName.PROJECT_MANAGER)
    others = client.get("/api/v1/runs", headers=pm2).json()
    assert all(run["id"] != run_id for run in others)


async def test_runs_list_respects_limit(client, auth_headers, make_project, cleaner) -> None:  # noqa: ANN001
    pm = await auth_headers(role=RoleName.PROJECT_MANAGER)
    await make_project(owner_id=pm["user"])

    for _ in range(2):
        created = client.post(
            "/api/v1/runs",
            headers=pm,
            json={"intent": "project_overview", "objective": "概览"},
        )
        assert created.status_code == 201, created.text
        cleaner("agent_runs", "id", created.json()["id"])

    listed = client.get("/api/v1/runs?limit=1", headers=pm)
    assert listed.status_code == 200
    assert len(listed.json()) <= 1
