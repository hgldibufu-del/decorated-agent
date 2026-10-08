"""RAG 证据底座集成测试 —— Phase 4（需要真实 PostgreSQL + pgvector）。

覆盖：文档写入 + 向量检索（余弦）、BM25 词法检索、按元数据过滤的相似案例、混合检索。
"""

from __future__ import annotations

import uuid

from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_infrastructure.rag.embeddings import FakeEmbedder
from dw_infrastructure.rag.retrieval import IdentityReranker, retrieve
from dw_infrastructure.rag.store import DocumentStore


def _store(session) -> DocumentStore:
    settings = get_settings()
    return DocumentStore(session, FakeEmbedder(settings.rag_embedding_dim), settings.rag_embedding_dim)


async def test_rag_vector_search_finds_nearest() -> None:
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        store = _store(session)
        src = f"rag-{uuid.uuid4().hex}"
        await store.upsert_document(
            title="防水", content="卫生间渗水漏水，需做闭水试验排查防水渗漏点。", source=src
        )
        await store.upsert_document(
            title="报价", content="装修报价预算造价，套餐材料价格。", source=src
        )
        await store.upsert_document(
            title="设计", content="户型布局设计方案效果图。", source=src
        )

        hits = await store.vector_search("卫生间漏水", k=2)
        assert hits, "向量检索应返回结果"
        # 最近邻应属于防水文档（与查询共享「渗水/漏水」token）
        assert "渗水" in hits[0].content or "漏水" in hits[0].content
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores)  # 余弦距离升序
        await store.clear()
    await database.dispose()


async def test_rag_bm25_search_on_ascii() -> None:
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        store = _store(session)
        src = f"rag-{uuid.uuid4().hex}"
        await store.upsert_document(
            title="leak",
            content="The bathroom has a water leak and moisture problem.",
            source=src,
        )
        await store.upsert_document(
            title="quote",
            content="The renovation quote and budget estimation.",
            source=src,
        )

        hits = await store.bm25_search("leak", k=2)
        assert hits and "leak" in hits[0].content.lower()
        await store.clear()
    await database.dispose()


async def test_rag_similar_cases_filters_by_metadata() -> None:
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        store = _store(session)
        src = f"rag-{uuid.uuid4().hex}"
        await store.upsert_document(
            title="case1",
            content="卫生间渗水维修案例：重做防水层后解决。",
            source=src,
            metadata={"kind": "case", "case_id": "C1"},
        )
        await store.upsert_document(
            title="kb", content="卫生间渗水的一般处理方法。", source=src, metadata={"kind": "kb"}
        )

        cases = await store.similar_cases("卫生间渗水", k=3)
        assert cases, "应匹配到历史案例"
        assert all(item.metadata.get("kind") == "case" for item in cases)
        await store.clear()
    await database.dispose()


async def test_rag_hybrid_retrieve() -> None:
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        store = _store(session)
        src = f"rag-{uuid.uuid4().hex}"
        await store.upsert_document(
            title="t", content="卫生间渗水漏水维修与排查。", source=src
        )

        result = await retrieve(store, "卫生间漏水", k=3, reranker=IdentityReranker())
        assert result.strategy.startswith("hybrid")
        assert result.chunks
        await store.clear()
    await database.dispose()
