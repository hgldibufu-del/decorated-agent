"""参考数据只读 + 建档接口 —— 需求文档 §9 / §21。

「新建项目」需要 customer_id + house_id，「添加成员」需要候选 user_id，
而这些参考数据此前没有端点。这里补齐最小集合：

* `GET/POST /customers`、`GET/POST /houses`、`GET /users`。

写操作与 `POST /projects` 一致要求 `project:write`；查询同样以 `project:write` 收敛
（这些数据只服务于项目管理，不需要对普通查看者开放）。
"""

from __future__ import annotations

from uuid import UUID

from dw_domain.services import ProjectService
from dw_schemas.iam import UserBrief, UserIdentity
from dw_schemas.project import (
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    HouseCreate,
    HouseOut,
    HouseUpdate,
)
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import current_identity, get_db_session

router = APIRouter(tags=["reference"])


@router.get("/customers", response_model=list[CustomerOut], summary="列出客户")
async def list_customers(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[CustomerOut]:
    return await ProjectService(session).list_customers(identity)


@router.post(
    "/customers",
    response_model=CustomerOut,
    status_code=201,
    summary="新建客户",
    responses={409: {"description": "手机号已存在"}},
)
async def create_customer(
    payload: CustomerCreate,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerOut:
    return await ProjectService(session).create_customer(payload, identity)


@router.get("/houses", response_model=list[HouseOut], summary="列出房屋（可按客户过滤）")
async def list_houses(
    customer_id: UUID | None = Query(default=None),
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[HouseOut]:
    return await ProjectService(session).list_houses(identity, customer_id=customer_id)


@router.post(
    "/houses",
    response_model=HouseOut,
    status_code=201,
    summary="新建房屋",
    responses={404: {"description": "客户不存在"}},
)
async def create_house(
    payload: HouseCreate,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> HouseOut:
    return await ProjectService(session).create_house(payload, identity)


@router.put(
    "/customers/{customer_id}",
    response_model=CustomerOut,
    summary="编辑客户",
    responses={409: {"description": "手机号已存在"}},
)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerOut:
    return await ProjectService(session).update_customer(customer_id, payload, identity)


@router.delete(
    "/customers/{customer_id}",
    status_code=204,
    response_class=Response,
    summary="删除客户",
    responses={409: {"description": "名下仍有房屋，无法删除"}},
)
async def delete_customer(
    customer_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await ProjectService(session).delete_customer(customer_id, identity)
    return Response(status_code=204)


@router.put(
    "/houses/{house_id}",
    response_model=HouseOut,
    summary="编辑房屋",
)
async def update_house(
    house_id: UUID,
    payload: HouseUpdate,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> HouseOut:
    return await ProjectService(session).update_house(house_id, payload, identity)


@router.delete(
    "/houses/{house_id}",
    status_code=204,
    response_class=Response,
    summary="删除房屋",
    responses={409: {"description": "仍被项目引用，无法删除"}},
)
async def delete_house(
    house_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await ProjectService(session).delete_house(house_id, identity)
    return Response(status_code=204)


@router.get("/users", response_model=list[UserBrief], summary="成员候选用户")
async def list_users(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserBrief]:
    return await ProjectService(session).list_users(identity)
