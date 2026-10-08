"""phase5 quote business tables

Revision ID: 6b2c3d4e5f60
Revises: 5a1b2c3d4e5f
Create Date: 2026-10-05 11:00:00.000000

Phase 5 报价估算 Specialist 的业务表：
* `quote_packages`（整装套餐：基础费 + 面积单价 + 包含范围）；
* `quote_items`（工艺 / 材料项：用于预算明细拆解与材料检索）。
金额统一 NUMERIC(12,2)。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6b2c3d4e5f60"
down_revision: str | None = "5a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "quote_packages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("base_price", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("price_per_sqm", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("included_scope", _JSONB, nullable=True),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_packages")),
        sa.UniqueConstraint("name", name=op.f("uq_quote_packages_name")),
    )

    op.create_table(
        "quote_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("metadata_json", _JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_items")),
    )


def downgrade() -> None:
    op.drop_table("quote_items")
    op.drop_table("quote_packages")
