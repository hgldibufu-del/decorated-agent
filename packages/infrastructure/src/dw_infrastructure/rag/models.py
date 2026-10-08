"""RAG 持久化模型 —— Phase 4。

两张表：
    rag_documents        被索引的知识文档（标题 / 来源 / 元数据）
    rag_document_chunks  文档切片，带 `embedding vector(<dim>)`（pgvector）

向量维度来自 `Settings.rag_embedding_dim`，与迁移建表维度保持一致（单一事实源 = 配置）。
模型子类 `dw_domain.models.Base`，因此 Alembic 的 `target_metadata` 能自动纳入。
"""

from __future__ import annotations

import uuid
from uuid import UUID

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from dw_infrastructure.config import get_settings
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# 维度在导入时确定（来自配置），与迁移脚本读取同一来源
EMBEDDING_DIM = get_settings().rag_embedding_dim


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "rag_documents"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "rag_document_chunks"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # pgvector 向量列；写入走文本绑定，读取走 `embedding <=> cast(:q as vector)`
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
