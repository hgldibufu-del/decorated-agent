"""施工业务表 —— Phase 7（Construction Specialist）。

与 Phase 5/6 同构：业务表驱动的确定性施工审查，不依赖 LLM，可解释、可测、零外部依赖。
* `construction_milestones`：**按项目**记录施工阶段（计划工期 vs 实际工期 + 状态），
  是 progress_analysis 的事实来源（沿用「项目域业务表」的 FK 策略：项目删除 → CASCADE）；
* `quality_checklists`：全局验收项标准（类目 + 验收标准 + 权重 + 严重度），供 quality_check 评估。
动态结构用 JSONB。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConstructionMilestone(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """施工阶段：某项目下「计划工期 / 实际工期 / 状态」。"""

    __tablename__ = "construction_milestones"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "stage", name="uq_construction_milestones_project_id_stage"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, comment="水电改造 / 泥瓦 …")
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="阶段顺序")
    planned_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_days: Mapped[int | None] = mapped_column(Integer, comment="未开始则为 NULL")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", comment="completed / in_progress / pending"
    )
    standard: Mapped[str | None] = mapped_column(String(500), comment="该阶段验收标准")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class QualityChecklist(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """验收项标准：类目 + 检查项 + 验收标准 + 权重 + 严重度（全局模板）。"""

    __tablename__ = "quality_checklists"

    category: Mapped[str] = mapped_column(String(64), nullable=False, comment="水电 / 防水 / 泥瓦 …")
    item: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    standard: Mapped[str | None] = mapped_column(String(500))
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="评分权重")
    severity: Mapped[str | None] = mapped_column(String(16), comment="高 / 中 / 低")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
