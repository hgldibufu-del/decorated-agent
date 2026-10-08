"""phase10 user memory table

Revision ID: 9e5f60718293
Revises: 8d4e5f607182
Create Date: 2026-10-05 18:00:00.000000

Phase 10 记忆层：`user_memories`（用户长期偏好 / 约束 / 事实）。

* 按 `(user_id, kind, key)` 唯一 → 同一偏好反复抽取也只留一行（幂等 upsert）；
* 用户注销 → CASCADE 清除，不留无法归属的偏好；
* `value` 用 JSONB（风格名 / 布尔标记 / 类目清单形态不一），金额无关。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9e5f60718293"
down_revision: str | None = "8d4e5f607182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", _JSONB, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_memories")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_memories_user_id"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "kind", "key", name="uq_user_memories_user_id_kind_key"
        ),
    )
    op.create_index(
        op.f("ix_user_memories_user_id"), "user_memories", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_memories_user_id"), table_name="user_memories")
    op.drop_table("user_memories")
