"""检索评估指标单测 —— Phase 9（纯函数，无需数据库）。"""

from __future__ import annotations

import json

import pytest
from dw_infrastructure.evaluation import (
    aggregate,
    hit_at_k,
    load_golden,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_case,
)


def test_hit_at_k_respects_cutoff():
    assert hit_at_k(["a", "b", "c"], ["c"], 2) == 0.0
    assert hit_at_k(["a", "b", "c"], ["c"], 3) == 1.0


def test_recall_at_k_counts_covered_relevant():
    assert recall_at_k(["a", "x", "b"], ["a", "b"], 3) == 1.0
    assert recall_at_k(["a", "x", "y"], ["a", "b"], 3) == 0.5
    # 无相关项时记 0，而不是除零
    assert recall_at_k(["a"], [], 3) == 0.0


def test_precision_at_k_is_over_returned_items():
    assert precision_at_k(["a", "x", "y"], ["a"], 3) == pytest.approx(1 / 3)
    assert precision_at_k([], ["a"], 3) == 0.0


def test_reciprocal_rank_uses_first_hit_rank():
    assert reciprocal_rank(["x", "a"], ["a"]) == 0.5
    assert reciprocal_rank(["a"], ["a"]) == 1.0
    assert reciprocal_rank(["x", "y"], ["a"]) == 0.0


def test_score_case_combines_all_metrics():
    score = score_case("q", ["x", "a"], ["a"], 3)
    assert (score.hit, score.recall, score.precision, score.rr) == (1.0, 1.0, 0.5, 0.5)


def test_aggregate_is_macro_average():
    metrics = aggregate(
        [
            score_case("q1", ["a"], ["a"], 3),
            score_case("q2", ["x", "y", "z"], ["a"], 3),
        ]
    )
    assert metrics.cases == 2
    assert metrics.hit_at_k == 0.5
    assert metrics.recall_at_k == 0.5
    assert metrics.mrr == 0.5


def test_aggregate_of_empty_is_zero():
    metrics = aggregate([])
    assert metrics.cases == 0
    assert metrics.as_dict()["mrr"] == 0.0


def test_builtin_golden_set_is_valid():
    golden = load_golden()
    assert golden.k == 3
    assert len(golden.documents) == 8
    assert len(golden.cases) == 8
    known = {document.key for document in golden.documents}
    for case in golden.cases:
        assert set(case.relevant) <= known


def test_load_golden_rejects_unknown_document_key(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "documents": [{"key": "a", "content": "内容"}],
                "cases": [{"query": "q", "relevant": ["missing"]}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="不存在"):
        load_golden(path)


def test_load_golden_rejects_empty_dataset(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"documents": [], "cases": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="不完整"):
        load_golden(path)
