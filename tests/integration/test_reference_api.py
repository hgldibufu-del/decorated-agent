"""参考数据端点集成测试（客户 / 房屋 / 成员候选用户）。

覆盖「新建项目」与「添加成员」所依赖的最小参考数据闭环。
"""

from __future__ import annotations

from uuid import uuid4

from dw_schemas.iam import RoleName


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


async def test_create_customer_and_house(client, auth_headers, cleaner) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    created = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "集成客户", "phone": _uniq("139")[:32]},
    )
    assert created.status_code == 201, created.text
    customer = created.json()
    cleaner("customers", "id", customer["id"])

    listed = client.get("/api/v1/customers", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == customer["id"] for item in listed.json())

    house = client.post(
        "/api/v1/houses",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "address": _uniq("地址"),
            "city": "上海",
            "area_sqm": "88.50",
            "layout": "两室两厅",
        },
    )
    assert house.status_code == 201, house.text
    house_body = house.json()
    cleaner("houses", "id", house_body["id"])
    assert house_body["area_sqm"] == "88.50"

    filtered = client.get(
        f"/api/v1/houses?customer_id={customer['id']}", headers=headers
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [house_body["id"]]


async def test_create_house_requires_existing_customer(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.post(
        "/api/v1/houses",
        headers=headers,
        json={"customer_id": str(uuid4()), "address": _uniq("地址")},
    )

    assert response.status_code == 404


async def test_users_are_available_as_member_candidates(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.get("/api/v1/users", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body, "至少应包含当前用户"
    assert {"id", "email", "full_name"} <= set(body[0].keys())


async def test_reference_write_requires_project_write_permission(client, auth_headers) -> None:  # noqa: ANN001
    # VIEWER 只有 project:read，不能建客户 / 房屋
    headers = await auth_headers(role=RoleName.VIEWER)

    response = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "无权限", "phone": _uniq("138")[:32]},
    )

    assert response.status_code == 403, response.text
