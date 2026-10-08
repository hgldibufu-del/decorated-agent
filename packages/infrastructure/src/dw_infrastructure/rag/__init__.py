"""RAG 流水线 —— Phase 4（数据层 + 检索层，不绑任何业务）。

设计要点：
* 嵌入器做成协议（Protocol），`FakeEmbedder` 确定性、零外部依赖，供 CI/测试；
  `OpenAIEmbedder` 为真实嵌入器的可插拔接缝（gated by Settings）；
* 向量检索走 pgvector 的 `<=>` 余弦距离，BM25 走 Postgres `tsvector`/`ts_rank`；
* 混合检索 = 向量 + BM25 → RRF 融合 → Reranker 接缝 → 返回带 provenance 的结果；
* 全程**不依赖 asyncpg 的二进制 vector codec**：写入用 pgvector.sqlalchemy 的文本绑定，
  读取用 `embedding <=> cast(:q as vector)` + `embedding::text`，只依赖服务端 pgvector 扩展。
"""

from __future__ import annotations

from dw_infrastructure.rag.embeddings import Embedder, FakeEmbedder, OpenAIEmbedder, build_embedder
from dw_infrastructure.rag.retrieval import (
    IdentityReranker,
    Reranker,
    RetrievalService,
    fuse_scores,
    retrieve,
)
from dw_infrastructure.rag.store import DocumentStore, ScoredChunk

__all__ = [
    "Embedder",
    "FakeEmbedder",
    "OpenAIEmbedder",
    "build_embedder",
    "DocumentStore",
    "ScoredChunk",
    "Reranker",
    "IdentityReranker",
    "RetrievalService",
    "fuse_scores",
    "retrieve",
]
