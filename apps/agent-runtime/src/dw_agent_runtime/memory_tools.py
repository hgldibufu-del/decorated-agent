"""记忆工具（受治理）—— Phase 10。

把「记忆」也接进完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计 / span）：
记忆的读写会出现在 Run 时间线、审计表与 trace 上，而不是藏在业务代码的角落里。

记忆是**按用户**的、与项目无关，因此这里不做 Project ACL ——
`memory:read` / `memory:write` 是唯一门禁（延续「工具能力 ≠ 数据权限，
但记忆本身没有项目维度」的界定）。
"""

from __future__ import annotations

from typing import Any

from dw_schemas.memory import MemoryCandidate, MemoryKind, MemoryValue
from pydantic import BaseModel, Field

from dw_agent_runtime.tools import RiskLevel, ToolContext, ToolDefinition
from dw_infrastructure.memory import PostgresMemoryStore


class MemoryRecallIn(BaseModel):
    kinds: list[MemoryKind] = Field(
        default_factory=list, description="按类别筛选；留空表示全部类别"
    )
    limit: int = Field(default=20, ge=1, le=200)


async def _memory_recall(payload: MemoryRecallIn, ctx: ToolContext) -> dict[str, Any]:
    store = PostgresMemoryStore(ctx.session)
    kinds = [kind.value for kind in payload.kinds] or None
    items = await store.recall(ctx.actor.user_id, kinds=kinds, limit=payload.limit)
    if items:
        # 召回即「使用」：留下 hits / last_used_at，便于后续判断哪些记忆是活的
        await store.touch([item.id for item in items])
    return {
        "user_id": str(ctx.actor.user_id),
        "items": [item.model_dump(mode="json") for item in items],
    }


class MemoryRememberIn(BaseModel):
    kind: MemoryKind = MemoryKind.PREFERENCE
    key: str = Field(..., min_length=1, max_length=128)
    value: MemoryValue
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


async def _memory_remember(payload: MemoryRememberIn, ctx: ToolContext) -> dict[str, Any]:
    store = PostgresMemoryStore(ctx.session)
    stored = await store.remember(
        ctx.actor.user_id,
        [
            MemoryCandidate(
                kind=payload.kind,
                key=payload.key,
                value=payload.value,
                confidence=payload.confidence,
            )
        ],
        source="manual",
    )
    return {"item": stored[0].model_dump(mode="json")}


MEMORY_TOOLS: dict[str, ToolDefinition[Any]] = {
    "memory_recall": ToolDefinition(
        tool_id="memory_recall",
        description="召回当前用户的长期记忆（偏好 / 约束 / 事实）",
        required_scopes=("memory:read",),
        risk_level=RiskLevel.L0,
        input_model=MemoryRecallIn,
        handler=_memory_recall,
    ),
    "memory_remember": ToolDefinition(
        tool_id="memory_remember",
        description="写入或更新当前用户的一条长期记忆（按 kind + key 幂等）",
        required_scopes=("memory:write",),
        risk_level=RiskLevel.L0,
        input_model=MemoryRememberIn,
        handler=_memory_remember,
    ),
}
