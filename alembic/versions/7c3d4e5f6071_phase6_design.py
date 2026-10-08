"""phase6 design business tables

Revision ID: 7c3d4e5f6071
Revises: 6b2c3d4e5f60
Create Date: 2026-10-05 14:00:00.000000

Phase 6 设计提案 Specialist 的业务表：
* `design_styles`（设计风格目录：风格族 + 适用户型 + 色板 + 特征 + 标签）；
* `layout_modules`（户型模块指南：房间类型 → 功能/原则/建议材料类目）。
动态结构用 JSONB，金额无关。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c3d4e5f6071"
down_revision: str | None = "6b2c3d4e5f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "design_styles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("style_family", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("suitable_layouts", _JSONB, nullable=True),
        sa.Column("palette", _JSONB, nullable=True),
        sa.Column("characteristics", _JSONB, nullable=True),
        sa.Column("tags", _JSONB, nullable=True),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_design_styles")),
        sa.UniqueConstraint("name", name=op.f("uq_design_styles_name")),
    )

    op.create_table(
        "layout_modules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("room_type", sa.String(length=64), nullable=False),
        sa.Column("suggested_function", sa.String(length=500), nullable=True),
        sa.Column("design_principle", sa.String(length=2000), nullable=True),
        sa.Column("recommended_material_category", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_layout_modules")),
        sa.UniqueConstraint("room_type", name=op.f("uq_layout_modules_room_type")),
    )


def downgrade() -> None:
    op.drop_table("layout_modules")
    op.drop_table("design_styles")
