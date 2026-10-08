"""Project ACL 端到端：可见性收敛与写操作管控。"""

from __future__ import annotations

from uuid import uuid4

from dw_schemas.iam import ProjectRole, RoleName


def bearer_for(client, user: dict[str, str]) -> dict[str, str]:
    """用给定自建账号换取 Authorization 头（不借助 auth_headers 夹具）。"""
    login = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_non_member_cannot_read_project(client, auth_headers, make_project):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    # 设计师持有 project:read，但不是该项目成员
    outsider = await auth_headers(role=RoleName.DESIGNER)

    response = client.get(f"/api/v1/projects/{project['id']}", headers=outsider)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_member_with_viewer_membership_can_read(
    client, auth_headers, make_project, make_user
):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    viewer = await make_user(role=RoleName.VIEWER)
    added = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": viewer["id"], "role": ProjectRole.VIEWER.value},
    )
    assert added.status_code == 200, added.text

    response = client.get(f"/api/v1/projects/{project['id']}", headers=bearer_for(client, viewer))
    assert response.status_code == 200


async def test_viewer_member_cannot_manage_members(client, auth_headers, make_project, make_user):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    viewer = await make_user(role=RoleName.VIEWER)
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": viewer["id"], "role": ProjectRole.VIEWER.value},
    )

    stranger = await make_user(role=RoleName.DESIGNER)
    response = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=bearer_for(client, viewer),
        json={"user_id": stranger["id"], "role": ProjectRole.MEMBER.value},
    )

    assert response.status_code == 403


async def test_owner_adds_member_and_duplicate_call_updates_role(
    client, auth_headers, make_project, make_user
):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])
    designer = await make_user(role=RoleName.DESIGNER)

    first = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": designer["id"], "role": ProjectRole.MEMBER.value},
    )
    assert first.status_code == 200
    assert any(member["user_id"] == designer["id"] for member in first.json())

    second = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": designer["id"], "role": ProjectRole.MANAGER.value},
    )
    assert second.status_code == 200
    entries = [member for member in second.json() if member["user_id"] == designer["id"]]
    # 幂等：重复添加只更新角色，不产生第二条成员关系
    assert len(entries) == 1
    assert entries[0]["role"] == ProjectRole.MANAGER.value


async def test_adding_unknown_user_returns_404(client, auth_headers, make_project):
    owner = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=owner["user"])

    response = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner,
        json={"user_id": str(uuid4()), "role": ProjectRole.MEMBER.value},
    )

    assert response.status_code == 404


async def test_list_returns_only_accessible_projects(client, auth_headers, make_project):
    alice = await auth_headers(role=RoleName.PROJECT_MANAGER)
    bob = await auth_headers(role=RoleName.PROJECT_MANAGER)

    project_a = await make_project(owner_id=alice["user"])
    project_b = await make_project(owner_id=bob["user"])

    listing = client.get("/api/v1/projects", headers=alice)
    assert listing.status_code == 200
    visible = {item["id"] for item in listing.json()}
    assert project_a["id"] in visible
    assert project_b["id"] not in visible


async def test_admin_sees_projects_without_membership(client, auth_headers, make_project):
    pm = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=pm["user"])
    admin = await auth_headers(role=RoleName.ADMIN)

    assert client.get(f"/api/v1/projects/{project['id']}", headers=admin).status_code == 200

    listing = client.get("/api/v1/projects", headers=admin)
    entry = next(item for item in listing.json() if item["id"] == project["id"])
    # admin 不是成员，member_role 应为 None
    assert entry["member_role"] is None
