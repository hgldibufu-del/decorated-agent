"""记忆路由 —— Phase 10（REST 入口）。

Controller 只做三件事：取身份 → 调记忆存储 → 返回契约；幂等与唯一性在
`dw_infrastructure.memory`，这里一条业务 SQL 都没有。

**不接受 `user_id` 参数**：记忆是「当前用户自己的」，从令牌取身份即可，
否则「改一个 id 就能读写别人的偏好」会成为一个越权面。
"""

from __future__ import annotations

from dw_infrastructure.memory import PostgresMemoryStore
from dw_schemas.iam import PermissionCode, UserIdentity
from dw_schemas.memory import (
    MemoryCandidate,
    MemoryDeleteOut,
    MemoryItem,
    MemoryUpsertIn,
)
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import get_db_session, require_permissions

router = APIRouter(tags=["memory"])


@router.get(
    "/memories",
    response_model=list[MemoryItem],
    summary="列出我的长期记忆（按置信度 / 更新时间排序）",
)
async def list_memories(
    identity: UserIdentity = Depends(require_permissions(PermissionCode.MEMORY_READ)),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryItem]:
    return await PostgresMemoryStore(session).recall(identity.user_id)


@router.post(
    "/memories",
    response_model=MemoryItem,
    summary="写入或更新一条记忆（按 kind + key 幂等）",
)
async def upsert_memory(
    payload: MemoryUpsertIn,
    identity: UserIdentity = Depends(require_permissions(PermissionCode.MEMORY_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryItem:
    stored = await PostgresMemoryStore(session).remember(
        identity.user_id,
        [MemoryCandidate(**payload.model_dump())],
        source="manual",
    )
    return stored[0]


@router.delete(
    "/memories/{key}",
    response_model=MemoryDeleteOut,
    summary="删除我的一条记忆（按 key；返回实际删除条数）",
)
async def delete_memory(
    key: str,
    identity: UserIdentity = Depends(require_permissions(PermissionCode.MEMORY_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryDeleteOut:
    deleted = await PostgresMemoryStore(session).forget(identity.user_id, key=key)
    return MemoryDeleteOut(deleted=deleted)
