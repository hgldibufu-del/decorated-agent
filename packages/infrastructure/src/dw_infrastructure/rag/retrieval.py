"""混合检索 —— Phase 4。

向量检索（语义）+ BM25（词法）→ RRF 融合 → Reranker 接缝。
`fuse_scores` 是纯函数，可单测；`retrieve` 组合 store 的两路检索与融合。
Reranker 只留接口 + `IdentityReranker` 占位，真实 cross-encoder 重排是后续接缝。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from dw_schemas.rag import RetrievedChunk, RetrievalResult
from dw_infrastructure.observability import record_ok, start_span
from dw_infrastructure.rag.store import DocumentStore, ScoredChunk

RRF_K = 60


def fuse_scores(
    vector_ids: Sequence[str],
    bm25_ids: Sequence[str],
    k: int = 5,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：把两路排序融合成单一排序。

    对每路结果按出现顺序给 rank（从 1 开始），得分 = Σ 1/(K+rank)。
    纯函数，无 IO，便于单测断言排序正确性。
    """

    def _rank_scores(ids: Sequence[str]) -> dict[str, float]:
        return {item_id: 1.0 / (RRF_K + rank) for rank, item_id in enumerate(ids, start=1)}

    scores_vector = _rank_scores(vector_ids)
    scores_bm25 = _rank_scores(bm25_ids)
    merged: dict[str, float] = {}
    for item_id in set(vector_ids) | set(bm25_ids):
        merged[item_id] = scores_vector.get(item_id, 0.0) + scores_bm25.get(item_id, 0.0)
    return sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:k]


@runtime_checkable
class Reranker(Protocol):
    """重排器协议：对融合后的候选做二次精排（可插拔 cross-encoder）。"""

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]: ...


class IdentityReranker:
    """占位重排器：原样返回（融合排序即最终排序）。"""

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        return chunks


async def retrieve(
    store: DocumentStore,
    query: str,
    *,
    k: int = 5,
    vector_k: int = 10,
    bm25_k: int = 10,
    reranker: Reranker | None = None,
) -> RetrievalResult:
    """混合检索入口；外包一层 `rag.retrieve` span（未启用追踪时为 no-op）。

    刻意**不记录 query 原文**（可能含客户敏感信息），只记录规模与最终策略。
    """
    with start_span(
        "rag.retrieve",
        attributes={"rag.k": k, "rag.vector_k": vector_k, "rag.bm25_k": bm25_k},
    ) as span:
        result = await _retrieve(
            store, query, k=k, vector_k=vector_k, bm25_k=bm25_k, reranker=reranker
        )
        span.set_attribute("rag.strategy", result.strategy)
        span.set_attribute("rag.chunk_count", len(result.chunks))
        record_ok(span)
        return result


async def _retrieve(
    store: DocumentStore,
    query: str,
    *,
    k: int = 5,
    vector_k: int = 10,
    bm25_k: int = 10,
    reranker: Reranker | None = None,
) -> RetrievalResult:
    """混合检索：向量 + BM25 → RRF 融合 → 重排 → 带 provenance 的结果。"""
    vector_hits = await store.vector_search(query, k=vector_k)
    bm25_hits = await store.bm25_search(query, k=bm25_k)

    vector_ids = [hit.id.hex for hit in vector_hits]
    bm25_ids = [hit.id.hex for hit in bm25_hits]
    fused = fuse_scores(vector_ids, bm25_ids, k=k)

    by_id = {hit.id.hex: hit for hit in (*vector_hits, *bm25_hits)}
    chunks: list[RetrievedChunk] = []
    for rank, (item_id, score) in enumerate(fused, start=1):
        hit: ScoredChunk = by_id[item_id]
        chunks.append(
            RetrievedChunk(
                id=hit.id,
                document_id=hit.document_id,
                seq=hit.seq,
                content=hit.content,
                source=hit.source,
                metadata=hit.metadata,
                score=round(score, 6),
                rank=rank,
            )
        )

    reranker = reranker or IdentityReranker()
    chunks = await reranker.rerank(query, chunks)
    return RetrievalResult(query=query, strategy="hybrid(vector+bm25+rrf)", chunks=chunks)


class RetrievalService:
    """薄封装：持有 store，对外暴露一次检索调用。"""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def search(self, query: str, *, k: int = 5, **kwargs: object) -> RetrievalResult:
        return await retrieve(self._store, query, k=k, **kwargs)
