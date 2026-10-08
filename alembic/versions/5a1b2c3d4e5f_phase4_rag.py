"""phase4 rag evidence store

Revision ID: 5a1b2c3d4e5f
Revises: 19e26bb488f7
Create Date: 2026-10-05 10:00:00.000000

RAG 证据底座（Phase 4）：
* 启用 pgvector 扩展（服务端向量检索）；
* 新建 `rag_documents` / `rag_document_chunks` 两张表，分块带 `embedding vector(<dim>)`；
* 建 HNSW 向量索引与 BM25 的 GIN 索引。
向量维度来自 `Settings.rag_embedding_dim`，与 `rag/models.py` 同一来源。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from dw_infrastructure.config import get_settings

revision: str = "5a1b2c3d4e5f"
down_revision: str | None = "4f1a2b3c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    dim = get_settings().rag_embedding_dim

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rag_documents")),
    )

    op.create_table(
        "rag_document_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False),
        sa.Column("embedding", Vector(dim), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["rag_documents.id"],
            name=op.f("fk_rag_document_chunks_document_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rag_document_chunks")),
    )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_rag_document_chunks_embedding "
            "ON rag_document_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_rag_document_chunks_content_tsv "
            "ON rag_document_chunks USING gin (to_tsvector('simple', content))"
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_document_chunks_content_tsv")
    op.execute("DROP INDEX IF EXISTS ix_rag_document_chunks_embedding")
    op.drop_table("rag_document_chunks")
    op.drop_table("rag_documents")
