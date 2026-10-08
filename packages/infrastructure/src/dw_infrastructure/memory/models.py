"""记忆持久化模型 —— Phase 10。

一张表：`user_memories`（长期偏好 / 约束 / 事实）。

子类化 `dw_domain.models.Base`：沿用 `dw_infrastructure/rag/models.py` 的先例
（基础设施层自带的 ORM 也挂在同一份 metadata 上，由 `alembic/env.py` 显式导入注册）。

幂等由 `uq_user_memories_user_id_kind_key` 保证：同一用户、同一类别、同一 key
只有一个值 —— 于是「反复从同一句 objective 抽取」不会堆积重复偏好。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class UserMemory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "key", name="uq_user_memories_user_id_kind_key"),
    )

    # 用户注销 → 记忆随之消失（CASCADE），不留下无法归属的偏好
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # 偏好值形态多样（风格名 / 布尔标记 / 类目清单）→ JSONB，真正动态的结构
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # 来源：`run:<id>` / `manual` / 未来 `mem0:<version>`，用于追溯「为什么会记得」
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
