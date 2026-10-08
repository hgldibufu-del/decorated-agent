"""检索评估指标 —— Phase 9。

全部是**纯函数**：无 IO、无随机、无 LLM，可离线复现，因此能作为 CI 回归阈值。
这也是与 RAGAS 的分工：RAGAS 的语义指标（answer relevancy / faithfulness）依赖
LLM 判官、非确定性；本模块只回答「检索有没有找对证据」这一客观问题。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def _top(retrieved: Sequence[str], k: int) -> list[str]:
    return list(retrieved[:k])


def hit_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """top-k 内是否命中至少一个相关项（1.0 / 0.0）。"""
    return 1.0 if set(_top(retrieved, k)) & set(relevant) else 0.0


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """top-k 覆盖了全部相关项的多少比例（相关项为空记 0，避免除零）。"""
    unique_relevant = set(relevant)
    if not unique_relevant:
        return 0.0
    return len(set(_top(retrieved, k)) & unique_relevant) / len(unique_relevant)


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """top-k 中有多少比例命中相关项（结果为空记 0）。"""
    top = _top(retrieved, k)
    if not top:
        return 0.0
    return len(set(top) & set(relevant)) / len(top)


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    """第一个相关项排名的倒数，未命中记 0（MRR 的单案组成）。"""
    relevant_set = set(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True, slots=True)
class CaseScore:
    """单个查询的得分（保留 retrieved 便于定位「为什么没命中」）。"""

    query: str
    hit: float
    recall: float
    precision: float
    rr: float
    retrieved: tuple[str, ...]


def score_case(
    query: str,
    retrieved: Sequence[str],
    relevant: Sequence[str],
    k: int,
) -> CaseScore:
    return CaseScore(
        query=query,
        hit=hit_at_k(retrieved, relevant, k),
        recall=recall_at_k(retrieved, relevant, k),
        precision=precision_at_k(retrieved, relevant, k),
        rr=reciprocal_rank(retrieved, relevant),
        retrieved=tuple(retrieved),
    )


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    """数据集级汇总（宏平均）。"""

    hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    cases: int

    def as_dict(self) -> dict[str, float]:
        return {
            "hit_at_k": round(self.hit_at_k, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "mrr": round(self.mrr, 4),
            "cases": self.cases,
        }


def aggregate(scores: Sequence[CaseScore]) -> AggregateMetrics:
    """宏平均：每案等权，避免长尾用例被个别用例稀释。"""
    if not scores:
        return AggregateMetrics(0.0, 0.0, 0.0, 0.0, 0)
    count = len(scores)
    return AggregateMetrics(
        hit_at_k=sum(score.hit for score in scores) / count,
        recall_at_k=sum(score.recall for score in scores) / count,
        precision_at_k=sum(score.precision for score in scores) / count,
        mrr=sum(score.rr for score in scores) / count,
        cases=count,
    )
