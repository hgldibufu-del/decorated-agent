"""phase7 construction business tables

Revision ID: 8d4e5f607182
Revises: 7c3d4e5f6071
Create Date: 2026-10-05 15:30:00.000000

Phase 7 施工审查 Specialist 的业务表：
* `construction_milestones`（按项目记录施工阶段：计划/实际工期 + 状态，FK → projects CASCADE）；
* `quality_checklists`（全局验收项标准：类目 + 检查项 + 权重 + 严重度）。
动态结构用 JSONB，金额无关。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d4e5f607182"
down_revision: str | None = "7c3d4e5f6071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "construction_milestones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("standard", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_construction_milestones")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name=op.f("fk_construction_milestones_project_id"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "stage", name="uq_construction_milestones_project_id_stage"
        ),
    )

    op.create_table(
        "quality_checklists",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("item", sa.String(length=200), nullable=False),
        sa.Column("standard", sa.String(length=500), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_checklists")),
        sa.UniqueConstraint("item", name=op.f("uq_quality_checklists_item")),
    )


def downgrade() -> None:
    op.drop_table("quality_checklists")
    op.drop_table("construction_milestones")
