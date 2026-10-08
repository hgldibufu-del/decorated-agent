"""检索评估执行器 —— Phase 9。

**隔离策略**：把 golden 语料写入 store 时，给 `source` 加本次运行独有的前缀；
评估时只保留同前缀的命中，并把前缀剥掉再与 document key 比对。这样：

* 不依赖、也不破坏库里既有数据（评估与在线数据互不干扰）；
* 指标只反映 golden 语料内部的排序质量，precision 不被无关文档稀释。

默认跑完即清理自己写入的语料（失败也清理），不给库留垃圾。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from dw_infrastructure.evaluation.golden import GoldenSet, load_golden
from dw_infrastructure.evaluation.metrics import (
    AggregateMetrics,
    CaseScore,
    aggregate,
    score_case,
)
from dw_infrastructure.rag.retrieval import RetrievalService
from dw_infrastructure.rag.store import DocumentStore


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset: str
    k: int
    metrics: AggregateMetrics
    cases: tuple[CaseScore, ...]
    ingested_documents: int

    def as_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "k": self.k,
            "ingested_documents": self.ingested_documents,
            "metrics": self.metrics.as_dict(),
            "cases": [
                {
                    "query": case.query,
                    "hit": case.hit,
                    "recall": case.recall,
                    "precision": case.precision,
                    "reciprocal_rank": case.rr,
                    "retrieved": list(case.retrieved),
                }
                for case in self.cases
            ],
        }


async def ingest_golden(
    store: DocumentStore, golden: GoldenSet, prefix: str
) -> dict[str, str]:
    """写入 golden 语料，返回 `document key → 带前缀 source` 映射。"""
    mapping: dict[str, str] = {}
    for document in golden.documents:
        source = f"{prefix}:{document.source}"
        await store.upsert_document(
            title=document.title,
            content=document.content,
            source=source,
            metadata=document.metadata,
        )
        mapping[document.key] = source
    return mapping


async def evaluate(
    store: DocumentStore, golden: GoldenSet, *, cleanup: bool = True
) -> EvaluationReport:
    """跑一次完整评估：摄入 golden 语料 → 逐案检索 → 打分 → 汇总。"""
    prefix = f"eval-{uuid4().hex}"
    mapping = await ingest_golden(store, golden, prefix)
    by_source = {source: key for key, source in mapping.items()}
    service = RetrievalService(store)
    try:
        scores: list[CaseScore] = []
        for case in golden.cases:
            result = await service.search(case.query, k=golden.k)
            # 只认本次评估语料的命中（同上：前缀即作用域）
            retrieved = [
                by_source[chunk.source] for chunk in result.chunks if chunk.source in by_source
            ]
            scores.append(score_case(case.query, retrieved, case.relevant, golden.k))
        return EvaluationReport(
            dataset=golden.name,
            k=golden.k,
            metrics=aggregate(scores),
            cases=tuple(scores),
            ingested_documents=len(golden.documents),
        )
    finally:
        if cleanup:
            for source in mapping.values():
                await store.delete_by_source(source)


async def evaluate_default(
    store: DocumentStore, path: Path | str | None = None
) -> EvaluationReport:
    return await evaluate(store, load_golden(path))
