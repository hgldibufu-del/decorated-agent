"""记忆存储 —— Phase 10。

`MemoryStore` 是**协议**而不是具体实现：这是 mem0ai / 向量记忆的接缝
（将来接真实向量检索，只需实现同一协议，编排与测试无需改动）。

`PostgresMemoryStore` 是确定性的默认实现：

* **幂等**：按 `(user_id, kind, key)` 命中则更新，否则插入；
* **并发**：唯一约束兜底 —— 真并发下数据库会拒绝第二条，而不是静默写出重复偏好；
* **可追溯**：每条记忆带 `source`（`run:<id>` / `manual`），能回答「为什么会记得」。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from dw_schemas.memory import MemoryCandidate, MemoryItem, MemoryKind
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dw_infrastructure.memory.models import UserMemory

# 单次召回上限：防止画像膨胀后把 payload 撑爆
MAX_RECALL_LIMIT = 200
DEFAULT_RECALL_LIMIT = 50


def _to_item(row: UserMemory) -> MemoryItem:
    return MemoryItem(
        id=row.id,
        kind=MemoryKind(row.kind),
        key=row.key,
        value=row.value,
        confidence=row.confidence,
        source=row.source,
        hits=row.hits,
        last_used_at=row.last_used_at,
        updated_at=row.updated_at,
    )


@runtime_checkable
class MemoryStore(Protocol):
    """记忆存储协议（mem0ai / 向量实现替换此处）。"""

    async def recall(
        self,
        user_id: UUID,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = DEFAULT_RECALL_LIMIT,
    ) -> list[MemoryItem]: ...

    async def remember(
        self,
        user_id: UUID,
        items: Sequence[MemoryCandidate],
        *,
        source: str = "",
    ) -> list[MemoryItem]: ...

    async def forget(
        self, user_id: UUID, *, key: str, kind: str | None = None
    ) -> int: ...

    async def touch(self, memory_ids: Sequence[UUID]) -> None: ...


class PostgresMemoryStore:
    """PostgreSQL 实现：记忆的单一事实源（Redis 明确不承担此职责）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recall(
        self,
        user_id: UUID,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = DEFAULT_RECALL_LIMIT,
    ) -> list[MemoryItem]:
        stmt = select(UserMemory).where(UserMemory.user_id == user_id)
        if kinds:
            stmt = stmt.where(UserMemory.kind.in_(list(kinds)))
        # 置信度优先，其次按更新时间：低置信度的旧偏好不该压过高置信度的新偏好
        stmt = stmt.order_by(UserMemory.confidence.desc(), UserMemory.updated_at.desc())
        stmt = stmt.limit(max(1, min(limit, MAX_RECALL_LIMIT)))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_item(row) for row in rows]

    async def remember(
        self,
        user_id: UUID,
        items: Sequence[MemoryCandidate],
        *,
        source: str = "",
    ) -> list[MemoryItem]:
        stored: list[MemoryItem] = []
        for candidate in items:
            existing = (
                await self._session.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.kind == candidate.kind.value,
                        UserMemory.key == candidate.key,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                row = UserMemory(
                    user_id=user_id,
                    kind=candidate.kind.value,
                    key=candidate.key,
                    value=candidate.value,
                    confidence=candidate.confidence,
                    source=source,
                )
                self._session.add(row)
            else:
                row = existing
                row.value = candidate.value
                row.confidence = candidate.confidence
                row.source = source

            await self._session.flush()
            await self._session.refresh(row, attribute_names=["updated_at"])
            stored.append(_to_item(row))
        return stored

    async def forget(self, user_id: UUID, *, key: str, kind: str | None = None) -> int:
        stmt = delete(UserMemory).where(
            UserMemory.user_id == user_id, UserMemory.key == key
        )
        if kind is not None:
            stmt = stmt.where(UserMemory.kind == kind)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def touch(self, memory_ids: Sequence[UUID]) -> None:
        ids = list(memory_ids)
        if not ids:
            return
        await self._session.execute(
            update(UserMemory)
            .where(UserMemory.id.in_(ids))
            .values(hits=UserMemory.hits + 1, last_used_at=func.now())
        )
        await self._session.flush()
