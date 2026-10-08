"""DAG 校验与拓扑分层 —— 需求文档 §7 / §32。

**纯函数、零 IO**，因为这是最容易被并发与依赖搞坏的地方：

* 只有没有依赖关系的任务才允许并行 —— 由拓扑分层保证；
* 必须限制最大任务数、最大 DAG 深度、最大并发 —— 否则 Supervisor 会被一句
  自然语言指令诱导成无限展开的调用树（§32 明确禁止）。
"""

from __future__ import annotations

from dw_domain.errors import PlanValidationError
from dw_schemas.supervisor import PlannerLimits, PlanStep


def index_steps(steps: list[PlanStep]) -> dict[str, PlanStep]:
    duplicates = sorted({step.task_key for step in steps} - set())
    if duplicates:  # pragma: no cover - 由 validate_plan 提前拦截
        raise PlanValidationError(f"重复的任务编号: {', '.join(duplicates)}")
    return {step.task_key: step for step in steps}


def validate_plan(steps: list[PlanStep], limits: PlannerLimits) -> list[list[PlanStep]]:
    """校验计划并返回可执行的拓扑分层（同层任务互不依赖，可并行）。

    依次检查：非空 → 任务数上限 → 编号唯一 → 依赖存在 → 无环 → 深度上限 → 单层并发上限。
    """
    if not steps:
        raise PlanValidationError("计划为空")

    if len(steps) > limits.max_steps:
        raise PlanValidationError(f"任务数 {len(steps)} 超过上限 {limits.max_steps}")

    seen: set[str] = set()
    for step in steps:
        if step.task_key in seen:
            raise PlanValidationError(f"重复的任务编号: {step.task_key}")
        seen.add(step.task_key)

    for step in steps:
        for dependency in step.depends_on:
            if dependency == step.task_key:
                raise PlanValidationError(f"任务 {step.task_key} 依赖了自己")
            if dependency not in seen:
                raise PlanValidationError(f"任务 {step.task_key} 依赖了不存在的任务: {dependency}")

    levels = topological_levels(steps)

    if len(levels) > limits.max_depth:
        raise PlanValidationError(f"DAG 深度 {len(levels)} 超过上限 {limits.max_depth}")

    for level in levels:
        if len(level) > limits.max_parallel:
            raise PlanValidationError(f"单层并发 {len(level)} 超过上限 {limits.max_parallel}")

    return levels


def topological_levels(steps: list[PlanStep]) -> list[list[PlanStep]]:
    """Kahn 算法分层。存在环时抛异常而不是静默丢任务。"""
    by_key = {step.task_key: step for step in steps}
    pending: dict[str, set[str]] = {step.task_key: set(step.depends_on) for step in steps}

    levels: list[list[PlanStep]] = []
    while pending:
        ready = sorted(key for key, deps in pending.items() if not deps)
        if not ready:
            raise PlanValidationError("计划存在循环依赖")
        levels.append([by_key[key] for key in ready])
        for key in ready:
            pending.pop(key)
        for deps in pending.values():
            deps.difference_update(ready)

    return levels


def upstream_keys(steps: list[PlanStep], task_key: str) -> list[str]:
    """返回某任务的直接上游（用于把上游 Artifact 注入下游输入，§34）。"""
    for step in steps:
        if step.task_key == task_key:
            return list(step.depends_on)
    return []
