"""DocumentStore —— Phase 4 的数据层。

封装 RAG 文档/分块的写入与检索：向量检索（pgvector 余弦距离）+ BM25（tsvector）。
读写都只依赖**服务端 pgvector 扩展**，不在客户端注册二进制向量 codec：
* 写入：`Vector` 列的 bind_processor 把向量转成文本 `[x,y,...]`，asyncpg 以 text 发送，
  Postgres 隐式 cast text→vector；
* 读取：`embedding <=> cast(:q as vector)` 计算距离并只回传 float（无需 vector codec）；
  `embedding::text` 仅在需要原文时显式转文本。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dw_infrastructure.rag.embeddings import Embedder
from dw_infrastructure.rag.models import Document, DocumentChunk

_SENTENCE_SPLIT = re.compile(r"[^\n。！？!?；;]+")
_VECTOR_FMT = lambda vec: "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """检索命中分块（内部传输结构，含得分）。"""

    id: uuid.UUID
    document_id: uuid.UUID
    seq: int
    content: str
    source: str
    metadata: dict[str, Any]
    score: float


def _split_text(content: str, window: int = 200) -> list[str]:
    """把文档切成片段：优先按句末标点断句，过长句子再按字符窗口切。"""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.findall(content) if s.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= window:
            chunks.append(sentence)
            continue
        for start in range(0, len(sentence), window):
            chunks.append(sentence[start : start + window])
    return chunks or [content.strip() or "empty"]


class DocumentStore:
    """RAG 文档/分块的读写。"""

    def __init__(self, session: AsyncSession, embedder: Embedder, dim: int) -> None:
        self._session = session
        self._embedder = embedder
        self._dim = dim

    async def upsert_document(
        self,
        *,
        title: str,
        content: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
        window: int = 200,
    ) -> uuid.UUID:
        """写入一篇文档及其分块（带嵌入）。幂等由调用方保证（按 source 去重）。"""
        document_id = uuid.uuid4()
        self._session.add(
            Document(
                id=document_id,
                title=title,
                source=source,
                metadata_json=metadata or {},
            )
        )
        texts = _split_text(content, window=window)
        vectors = await self._embedder.embed(texts)
        for seq, (text, vector) in enumerate(zip(texts, vectors)):
            if len(vector) != self._dim:
                raise ValueError(
                    f"嵌入维度不匹配：期望 {self._dim}，得到 {len(vector)}"
                )
            self._session.add(
                DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    seq=seq,
                    content=text,
                    source=source,
                    metadata_json=metadata or {},
                    embedding=vector,
                )
            )
        await self._session.flush()
        return document_id

    async def delete_by_source(self, source: str) -> None:
        await self._session.execute(
            text("DELETE FROM rag_document_chunks WHERE source = :source"),
            {"source": source},
        )
        await self._session.execute(
            text("DELETE FROM rag_documents WHERE source = :source"),
            {"source": source},
        )

    async def clear(self) -> None:
        """测试用：清空全部 RAG 数据。"""
        await self._session.execute(text("DELETE FROM rag_document_chunks"))
        await self._session.execute(text("DELETE FROM rag_documents"))

    # ------------------------------------------------------------------ 检索
    async def vector_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        """向量检索：按余弦距离升序返回最近邻。"""
        q = (await self._embedder.embed([query]))[0]
        rows = await self._session.execute(
            text(
                """
                SELECT id, document_id, seq, content, source, metadata_json,
                       embedding <=> cast(:q as vector) AS distance
                FROM rag_document_chunks
                ORDER BY distance
                LIMIT :k
                """
            ),
            {"q": _VECTOR_FMT(q), "k": k},
        )
        return [
            ScoredChunk(
                id=row.id,
                document_id=row.document_id,
                seq=row.seq,
                content=row.content,
                source=row.source,
                metadata=row.metadata_json,
                score=float(row.distance),
            )
            for row in rows
        ]

    async def bm25_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        """BM25 词法检索：基于 tsvector/ts_rank（'simple' 配置）。"""
        rows = await self._session.execute(
            text(
                """
                SELECT id, document_id, seq, content, source, metadata_json,
                       ts_rank(to_tsvector('simple', content),
                               plainto_tsquery('simple', :q)) AS rank
                FROM rag_document_chunks
                WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', :q)
                ORDER BY rank DESC
                LIMIT :k
                """
            ),
            {"q": query, "k": k},
        )
        return [
            ScoredChunk(
                id=row.id,
                document_id=row.document_id,
                seq=row.seq,
                content=row.content,
                source=row.source,
                metadata=row.metadata_json,
                score=float(row.rank),
            )
            for row in rows
        ]

    async def similar_cases(self, query: str, k: int = 3) -> list[ScoredChunk]:
        """按元数据 `kind='case'` 过滤，返回最相似的历史案例（用 1-距离 作为相似度）。"""
        q = (await self._embedder.embed([query]))[0]
        rows = await self._session.execute(
            text(
                """
                SELECT id, document_id, seq, content, source, metadata_json,
                       1 - (embedding <=> cast(:q as vector)) AS similarity
                FROM rag_document_chunks
                WHERE metadata_json->>'kind' = 'case'
                ORDER BY embedding <=> cast(:q as vector)
                LIMIT :k
                """
            ),
            {"q": _VECTOR_FMT(q), "k": k},
        )
        return [
            ScoredChunk(
                id=row.id,
                document_id=row.document_id,
                seq=row.seq,
                content=row.content,
                source=row.source,
                metadata=row.metadata_json,
                score=float(row.similarity),
            )
            for row in rows
        ]
