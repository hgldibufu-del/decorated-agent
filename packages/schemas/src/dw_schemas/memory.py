"""记忆层契约 —— Phase 10（长期偏好）。

形状放 `schemas` 的理由：记忆要跨三处流转 ——
`dw_infrastructure`（存储 / 抽取适配器）、`dw_agent_runtime`（编排注入）、
`dw_api`（REST），必须有一份共同契约，否则三处会各自演化出不同的字段名。

刻意选择：

* `value` 允许标量与字符串列表：偏好形态多样（风格名、布尔标记、类目清单），
  强行收窄成字符串会逼出「用逗号拼接」这类伪结构；
* `key` 用点分小写命名空间（`style` / `budget.sensitivity` / `focus.storage`），
  便于按前缀分组与做「一值一键」的幂等 upsert；
* 否定语义不进契约：`RuleBasedExtractor` 在抽取阶段就把「不要新中式」挡掉，
  不把「值为假」的偏好在存储层留成噪音。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MemoryKind(str, Enum):
    """记忆类别：区分「偏好」与「约束」，供召回时按需筛选。"""

    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    FACT = "fact"


MemoryValue = str | bool | int | float | list[str]


class MemoryCandidate(BaseModel):
    """待写入的记忆（抽取器 / 工具 / REST 的共同输出形状，无 id）。"""

    kind: MemoryKind
    key: str = Field(..., min_length=1, max_length=128)
    value: MemoryValue
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryItem(MemoryCandidate):
    """已落库的记忆条目。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str = ""
    hits: int = 0
    last_used_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryProfile(BaseModel):
    """某个用户的记忆画像（Run 执行前注入给技能的只读快照）。"""

    user_id: UUID
    items: list[MemoryItem] = Field(default_factory=list)

    def value_for(self, key: str) -> Any | None:
        """按键取值：置信度高者优先，同置信度取较新的一条。"""
        matched = [item for item in self.items if item.key == key]
        if not matched:
            return None
        matched.sort(key=lambda item: (-item.confidence, item.updated_at or datetime.min))
        return matched[0].value

    def as_notes(self) -> list[str]:
        """人类可读摘要，便于写进 Artifact 的 provenance，而不是只留一堆 JSON。"""
        return [f"{item.key}={item.value}" for item in self.items]


class MemoryUpsertIn(BaseModel):
    """REST 写入体（与工具入参同形，但不依赖工具的 Pydantic 模型）。"""

    kind: MemoryKind = MemoryKind.PREFERENCE
    key: str = Field(..., min_length=1, max_length=128)
    value: MemoryValue
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryDeleteOut(BaseModel):
    deleted: int = Field(..., description="实际删除的条目数（0 表示不存在）")
