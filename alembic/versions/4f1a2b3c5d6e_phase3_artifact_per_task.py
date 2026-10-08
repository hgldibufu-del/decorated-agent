"""phase3 artifact per task

Revision ID: 4f1a2b3c5d6e
Revises: 19e26bb488f7
Create Date: 2026-10-05 00:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4f1a2b3c5d6e"
down_revision: str | None = "19e26bb488f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧唯一键假设「一个 run 内每种 artifact_type 只有一份」，但并行 DAG 中
    # 同一技能的多个任务各自产出同类型 Artifact，会撞键。改为按任务独立版本。
    op.drop_constraint("uq_artifacts_run_id_type_version", "artifacts", type_="unique")
    op.add_column(
        "artifacts",
        sa.Column(
            "task_id",
            sa.UUID(),
            sa.ForeignKey("agent_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_artifacts_run_id_task_id_version",
        "artifacts",
        ["run_id", "task_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifacts_run_id_task_id_version", "artifacts", type_="unique")
    op.drop_column("artifacts", "task_id")
    op.create_unique_constraint(
        "uq_artifacts_run_id_type_version",
        "artifacts",
        ["run_id", "artifact_type", "version"],
    )
