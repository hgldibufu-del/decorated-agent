"""Reviewer 判定单测 —— §5 的四种决策。"""

from __future__ import annotations

from dw_agent_runtime.supervisor.reviewer import (
    RunReviewFacts,
    TaskReviewFact,
    review_run,
)
from dw_schemas.supervisor import ReviewDecision


def fact(
    task_key: str = "T-001",
    *,
    status: str = "completed",
    attempt: int = 1,
    has_artifact: bool = True,
    tool_call_count: int = 1,
    denied_calls: int = 0,
    retryable: bool = False,
) -> TaskReviewFact:
    return TaskReviewFact(
        task_key=task_key,
        status=status,
        attempt=attempt,
        has_artifact=has_artifact,
        tool_call_count=tool_call_count,
        denied_calls=denied_calls,
        retryable=retryable,
    )


def facts(tasks, pending_approval: bool = False, retry_limit: int = 1) -> RunReviewFacts:
    return RunReviewFacts(
        tasks=tuple(tasks), pending_approval=pending_approval, retry_limit=retry_limit
    )


def test_all_completed_passes():
    result = review_run(facts([fact(), fact("T-002")]))
    assert result.decision is ReviewDecision.PASS
    assert result.issues == []


def test_missing_tool_evidence_is_an_evidence_gap():
    result = review_run(facts([fact(tool_call_count=0)]))
    assert result.decision is ReviewDecision.FALLBACK
    assert result.evidence_gaps


def test_completed_without_artifact_is_inconsistent():
    result = review_run(facts([fact(has_artifact=False)]))
    assert result.decision is ReviewDecision.FALLBACK
    assert result.consistency_issues


def test_retryable_failure_suggests_retry():
    result = review_run(facts([fact(status="failed", retryable=True, attempt=1)]))
    assert result.decision is ReviewDecision.RETRY


def test_retries_exhausted_escalates_to_fallback():
    result = review_run(facts([fact(status="failed", retryable=True, attempt=3)]))
    assert result.decision is ReviewDecision.FALLBACK


def test_pending_approval_requires_human():
    result = review_run(facts([fact(status="awaiting_approval")], pending_approval=True))
    assert result.decision is ReviewDecision.HUMAN_REVIEW


def test_denied_tool_call_requires_human():
    result = review_run(facts([fact(denied_calls=1)]))
    assert result.decision is ReviewDecision.HUMAN_REVIEW
