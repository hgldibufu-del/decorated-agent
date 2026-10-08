"""RAG 证据检索契约 —— Phase 4。

定义「外部知识证据」的形状：文档、分块、检索结果。
这里只有形状，没有 IO（检索实现在 `dw_infrastructure.rag`）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Document(BaseModel):
    """一篇被索引的外部知识文档（如一份售后案例库、一份工艺标准）。"""

    id: UUID
    title: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class Chunk(BaseModel):
    """文档被切分后的一个片段，向量检索的最小单元。"""

    id: UUID
    document_id: UUID
    seq: int
    content: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(Chunk):
    """检索命中的分块，带融合得分与排序。"""

    score: float
    rank: int


class RetrievalResult(BaseModel):
    """一次混合检索的产出。"""

    query: str
    strategy: str
    chunks: list[RetrievedChunk]
