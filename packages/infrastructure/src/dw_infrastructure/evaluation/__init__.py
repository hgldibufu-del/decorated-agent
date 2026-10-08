"""评估 harness —— Phase 9。

对外暴露三件事：指标（纯函数）、golden set 加载、评估执行器。
RAGAS 若要接入，只需实现同等形状的指标替换 `metrics.py`，runner / 数据集无需改动。
"""

from dw_infrastructure.evaluation.golden import (
    GoldenCase,
    GoldenDocument,
    GoldenSet,
    default_dataset_path,
    load_golden,
)
from dw_infrastructure.evaluation.metrics import (
    AggregateMetrics,
    CaseScore,
    aggregate,
    hit_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_case,
)
from dw_infrastructure.evaluation.runner import (
    EvaluationReport,
    evaluate,
    evaluate_default,
    ingest_golden,
)

__all__ = [
    "AggregateMetrics",
    "CaseScore",
    "EvaluationReport",
    "GoldenCase",
    "GoldenDocument",
    "GoldenSet",
    "aggregate",
    "default_dataset_path",
    "evaluate",
    "evaluate_default",
    "hit_at_k",
    "ingest_golden",
    "load_golden",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "score_case",
]
