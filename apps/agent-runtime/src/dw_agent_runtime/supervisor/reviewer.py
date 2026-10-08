"""Reviewer —— 需求文档 §5。

Reviewer **不是重新生成一个答案**，它只做四件事：验证、检查、发现问题、决定是否通过。

判定顺序（先硬约束，后质量）：
1. 还有待审的高风险任务      → HUMAN_REVIEW
2. 出现权限拒绝的工具调用      → HUMAN_REVIEW（需要人来判断是不是授权配错了）
3. 存在未完成且可重试的任务    → RETRY
4. 存在不可恢复的失败 / 证据缺口 / 一致性问题 → FALLBACK
5. 无问题                    → PASS
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_schemas.supervisor import ReviewDecision, ReviewResult


@dataclass(frozen=True, slots=True)
class TaskReviewFact:
    """一次复核所需的任务事实（由执行器从数据库行整理而来）。"""

    task_key: str
    status: str
    attempt: int
    has_artifact: bool
    tool_call_count: int
    denied_calls: int
    retryable: bool


@dataclass(frozen=True, slots=True)
class RunReviewFacts:
    tasks: tuple[TaskReviewFact, ...]
    pending_approval: bool
    retry_limit: int


def review_run(facts: RunReviewFacts) -> ReviewResult:
    evidence_gaps: list[str] = []
    consistency_issues: list[str] = []
    retryable_failures: list[str] = []
    hard_failures: list[str] = []

    for task in facts.tasks:
        if task.status == "completed":
            if task.tool_call_count == 0:
                evidence_gaps.append(f"{task.task_key} 没有任何工具调用证据")
            if not task.has_artifact:
                consistency_issues.append(f"{task.task_key} 标记完成但没有产出 Artifact")
            continue

        if task.status == "awaiting_approval":
            continue

        if task.retryable and task.attempt <= facts.retry_limit:
            retryable_failures.append(task.task_key)
        else:
            hard_failures.append(f"{task.task_key} {task.status}")

    if facts.pending_approval:
        return ReviewResult(
            decision=ReviewDecision.HUMAN_REVIEW,
            issues=["存在待人工审批的任务"],
            evidence_gaps=evidence_gaps,
            consistency_issues=consistency_issues,
            recommended_action="审批通过后从检查点恢复执行",
        )

    denied = [task.task_key for task in facts.tasks if task.denied_calls > 0]
    if denied:
        return ReviewResult(
            decision=ReviewDecision.HUMAN_REVIEW,
            issues=[f"{key} 触发了权限拒绝的工具调用" for key in denied],
            evidence_gaps=evidence_gaps,
            consistency_issues=consistency_issues,
            recommended_action="核对调用方 scope 与项目成员关系后再放行",
        )

    if retryable_failures:
        return ReviewResult(
            decision=ReviewDecision.RETRY,
            issues=[f"{key} 可重试" for key in retryable_failures],
            evidence_gaps=evidence_gaps,
            consistency_issues=consistency_issues,
            recommended_action="对失败任务重试（不超过重试上限）",
        )

    issues = hard_failures + evidence_gaps + consistency_issues
    if issues:
        return ReviewResult(
            decision=ReviewDecision.FALLBACK,
            issues=issues,
            evidence_gaps=evidence_gaps,
            consistency_issues=consistency_issues,
            recommended_action="降级处理：返回已完成的 Artifact 并提示用户失败原因",
        )

    return ReviewResult(
        decision=ReviewDecision.PASS,
        recommended_action="可以交付最终结果",
    )
