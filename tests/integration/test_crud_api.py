"""编辑 / 删除（完整 CRUD）集成测试。

覆盖：项目乐观锁（成功 + 版本冲突 409）、被引用删除 409、客户/房屋 CRUD、缺权限 403。
"""

from __future__ import annotations

from uuid import uuid4

from dw_schemas.iam import RoleName


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


async def _create_customer(client, headers) -> dict:  # noqa: ANN001
    response = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "CRUD客户", "phone": _uniq("139")[:32]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_house(client, headers, customer_id: str) -> dict:  # noqa: ANN001
    response = client.post(
        "/api/v1/houses",
        headers=headers,
        json={
            "customer_id": customer_id,
            "address": _uniq("地址"),
            "area_sqm": "90.00",
            "layout": "三室两厅",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_project_update_and_optimistic_lock(
    client, auth_headers, make_project
) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])

    detail = client.get(f"/api/v1/projects/{project['id']}", headers=headers).json()
    version = detail["version"]
    assert version >= 1

    updated = client.put(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
        json={"version": version, "name": "改名后", "status": "active"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "改名后"
    assert body["status"] == "active"
    assert body["version"] == version + 1

    # 用过期 version 再改 → 乐观锁冲突 409
    conflict = client.put(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
        json={"version": version, "name": "再次改名"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "CONFLICT"


async def test_project_delete_when_referenced_by_run_is_conflict(
    client, auth_headers, make_project, cleaner
) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    project = await make_project(owner_id=headers["user"])

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "project_overview", "objective": "看概览"},
    )
    assert created.status_code == 201, created.text
    cleaner("agent_runs", "id", created.json()["id"])

    # 有 Run 引用该 project（FK RESTRICT）→ 删除被拒绝
    response = client.delete(f"/api/v1/projects/{project['id']}", headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CONFLICT"


async def test_customer_and_house_crud(client, auth_headers, cleaner) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await _create_customer(client, headers)
    cleaner("customers", "id", customer["id"])
    house = await _create_house(client, headers, customer["id"])
    cleaner("houses", "id", house["id"])

    edited = client.put(
        f"/api/v1/houses/{house['id']}", headers=headers, json={"area_sqm": "101.50"}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["area_sqm"] == "101.50"

    edited_customer = client.put(
        f"/api/v1/customers/{customer['id']}", headers=headers, json={"note": "VIP"}
    )
    assert edited_customer.status_code == 200, edited_customer.text
    assert edited_customer.json()["note"] == "VIP"

    # 房屋未被项目引用 → 可删；客户名下已无房屋 → 可删
    assert client.delete(f"/api/v1/houses/{house['id']}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/customers/{customer['id']}", headers=headers).status_code == 204


async def test_delete_blocked_when_referenced(client, auth_headers, cleaner) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await _create_customer(client, headers)
    cleaner("customers", "id", customer["id"])
    house = await _create_house(client, headers, customer["id"])
    cleaner("houses", "id", house["id"])

    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "code": _uniq("GC"),
            "name": "引用项目",
            "customer_id": customer["id"],
            "house_id": house["id"],
        },
    )
    assert project.status_code == 201, project.text
    cleaner("projects", "id", project.json()["id"])

    # 房屋被项目引用 / 客户被房屋引用 → 均 409
    blocked_house = client.delete(f"/api/v1/houses/{house['id']}", headers=headers)
    assert blocked_house.status_code == 409, blocked_house.text
    blocked_customer = client.delete(f"/api/v1/customers/{customer['id']}", headers=headers)
    assert blocked_customer.status_code == 409, blocked_customer.text


async def test_crud_requires_project_write_permission(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.VIEWER)

    response = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "无权限", "phone": _uniq("138")[:32]},
    )
    assert response.status_code == 403, response.text
