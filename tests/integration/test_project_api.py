"""项目接口端到端：创建 / 列表 / 详情 / 错误处理。"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from dw_schemas.iam import ProjectRole, RoleName


def uid(prefix: str = "GC") -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def project_payload(customer_id: str, house_id: str, **overrides) -> dict:
    base = {
        "code": uid(),
        "name": "集成新建项目",
        "customer_id": customer_id,
        "house_id": house_id,
    }
    base.update(overrides)
    return base


async def test_create_project_marks_creator_as_owner(
    client, auth_headers, cleaner, make_customer, make_house
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await make_customer()
    house = await make_house(customer_id=customer["id"])

    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json=project_payload(customer["id"], house["id"], budget_amount="250000.00"),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    cleaner("project_members", "project_id", body["id"])
    cleaner("projects", "id", body["id"])

    assert len(body["members"]) == 1
    assert body["members"][0]["role"] == ProjectRole.OWNER.value
    assert body["members"][0]["user_id"] == headers["user"]
    assert Decimal(str(body["budget_amount"])) == Decimal("250000.00")
    assert body["customer"]["id"] == customer["id"]
    assert body["house"]["id"] == house["id"]


async def test_created_project_appears_in_list_and_detail(
    client, auth_headers, cleaner, make_customer, make_house
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await make_customer()
    house = await make_house(customer_id=customer["id"])

    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json=project_payload(customer["id"], house["id"], name="列表可见性"),
    )
    project_id = created.json()["id"]
    cleaner("project_members", "project_id", project_id)
    cleaner("projects", "id", project_id)

    listing = client.get("/api/v1/projects", headers=headers)
    assert listing.status_code == 200
    matched = [item for item in listing.json() if item["id"] == project_id]
    assert len(matched) == 1
    assert matched[0]["member_role"] == ProjectRole.OWNER.value
    assert matched[0]["customer_name"] == "集成客户"

    detail = client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == project_id


async def test_duplicate_project_code_returns_409_with_field(
    client, auth_headers, cleaner, make_customer, make_house
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await make_customer()
    house = await make_house(customer_id=customer["id"])
    payload = project_payload(customer["id"], house["id"], name="重复编号")

    first = client.post("/api/v1/projects", headers=headers, json=payload)
    assert first.status_code == 201
    cleaner("project_members", "project_id", first.json()["id"])
    cleaner("projects", "id", first.json()["id"])

    second = client.post("/api/v1/projects", headers=headers, json=payload)

    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "CONFLICT"
    assert body["details"]["field"] == "code"


async def test_unknown_customer_returns_404(client, auth_headers, make_customer, make_house):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    customer = await make_customer()
    house = await make_house(customer_id=customer["id"])

    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "code": uid(),
            "name": "客户不存在",
            "customer_id": str(uuid4()),
            "house_id": house["id"],
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_house_of_another_customer_returns_400(
    client, auth_headers, make_customer, make_house
):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
    owner_customer = await make_customer()
    other_customer = await make_customer(name="另一个客户")
    other_house = await make_house(customer_id=other_customer["id"])

    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json=project_payload(owner_customer["id"], other_house["id"], name="房屋归属错误"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_missing_token_returns_401(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_user_without_project_write_cannot_create(
    client, auth_headers, make_customer, make_house
):
    """预算员持有 project:read，但没有 project:write → 403。"""
    headers = await auth_headers(role=RoleName.ESTIMATOR)
    customer = await make_customer()
    house = await make_house(customer_id=customer["id"])

    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json=project_payload(customer["id"], house["id"], name="无写权限"),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_malformed_project_id_is_validation_error(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.get("/api/v1/projects/not-a-uuid", headers=headers)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["problems"]


async def test_unknown_but_valid_project_id_returns_404(client, auth_headers):
    headers = await auth_headers(role=RoleName.PROJECT_MANAGER)

    response = client.get(f"/api/v1/projects/{uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
