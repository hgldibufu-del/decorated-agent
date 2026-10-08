"""RAG 纯逻辑单测 —— Phase 4（不依赖数据库）。

覆盖：FakeEmbedder 确定性 + 相似度区分度、RRF 融合排序、retrieve 组合与重排接缝。
"""

from __future__ import annotations

import uuid

import pytest

from dw_infrastructure.rag.embeddings import FakeEmbedder
from dw_infrastructure.rag.retrieval import IdentityReranker, fuse_scores, retrieve
from dw_infrastructure.rag.store import ScoredChunk


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


async def test_fake_embedder_is_deterministic() -> None:
    embedder = FakeEmbedder(dim=64)
    first = await embedder.embed(["卫生间渗水漏水"])
    second = await embedder.embed(["卫生间渗水漏水"])
    assert first == second


async def test_fake_embedder_similarity_reflects_shared_tokens() -> None:
    embedder = FakeEmbedder(dim=64)
    a, b, c = await embedder.embed(
        ["卫生间渗水漏水严重", "卫生间漏水渗水返潮", "报价造价预算套餐"]
    )
    assert _cosine(a, b) > _cosine(a, c)


async def test_fake_embedder_dimension_is_respected() -> None:
    embedder = FakeEmbedder(dim=32)
    vec = (await embedder.embed(["任意文本"]))[0]
    assert len(vec) == 32


def test_fuse_scores_ranks_union_higher_than_single() -> None:
    fused = fuse_scores(["a", "b", "c"], ["c", "d"], k=5)
    ids = [item[0] for item in fused]
    # "c" 同时出现在两路结果里，应排第一
    assert ids[0] == "c"
    assert set(ids) == {"a", "b", "c", "d"}


def test_fuse_scores_respects_k() -> None:
    fused = fuse_scores(list("abcdefg"), list("hijklmn"), k=3)
    assert len(fused) == 3


class _StubStore:
    def __init__(self, vector: list[ScoredChunk], bm25: list[ScoredChunk]) -> None:
        self._vector = vector
        self._bm25 = bm25
        self.calls: list[str] = []

    async def vector_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        self.calls.append("vector")
        return self._vector

    async def bm25_search(self, query: str, k: int = 5) -> list[ScoredChunk]:
        self.calls.append("bm25")
        return self._bm25


def _chunk(score: float) -> ScoredChunk:
    return ScoredChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        seq=0,
        content="chunk",
        source="s",
        metadata={},
        score=score,
    )


async def test_retrieve_merges_two_paths_and_assigns_ranks() -> None:
    store = _StubStore([_chunk(0.1), _chunk(0.2)], [_chunk(0.5)])
    result = await retrieve(store, "卫生间渗水", k=3)

    assert result.strategy.startswith("hybrid")
    assert set(store.calls) == {"vector", "bm25"}
    assert len(result.chunks) == 3
    # 排序第一的应是同时命中两路的 id；这里 stub 各不相同，但 RRF 仍应给出唯一排序
    assert [chunk.rank for chunk in result.chunks] == [1, 2, 3]


async def test_retrieve_applies_reranker() -> None:
    store = _StubStore([_chunk(0.1)], [_chunk(0.5)])

    class _ReverseReranker:
        async def rerank(self, query: str, chunks):  # noqa: ANN001
            return list(reversed(chunks))

    result = await retrieve(store, "q", k=3, reranker=_ReverseReranker())
    assert result.chunks[0].rank == 2  # 被反排了
