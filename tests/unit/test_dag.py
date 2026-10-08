"""DAG 校验与拓扑分层单测 —— §7 / §32 的限额约束。"""

from __future__ import annotations

import pytest
from dw_agent_runtime.supervisor.dag import topological_levels, validate_plan
from dw_domain.errors import PlanValidationError
from dw_schemas.supervisor import PlannerLimits, PlanStep


def step(key: str, *depends_on: str) -> PlanStep:
    return PlanStep(
        task_key=key,
        agent_id="supervisor_agent",
        skill_id="project_snapshot",
        objective=key,
        depends_on=list(depends_on),
    )


def limits(**overrides) -> PlannerLimits:
    base = {
        "max_steps": 8,
        "max_depth": 3,
        "max_parallel": 3,
        "deadline_ms": 30_000,
        "retry_limit": 1,
    }
    base.update(overrides)
    return PlannerLimits(**base)  # type: ignore[arg-type]


def test_single_task_is_one_level():
    levels = validate_plan([step("T-001")], limits())
    assert [[s.task_key for s in level] for level in levels] == [["T-001"]]


def test_independent_tasks_land_in_same_level():
    levels = validate_plan([step("T-001"), step("T-002")], limits())
    assert len(levels) == 1
    assert {s.task_key for s in levels[0]} == {"T-001", "T-002"}


def test_chain_produces_sequential_levels():
    levels = validate_plan(
        [step("T-001"), step("T-002", "T-001"), step("T-003", "T-002")], limits()
    )
    assert [[s.task_key for s in level] for level in levels] == [
        ["T-001"],
        ["T-002"],
        ["T-003"],
    ]


def test_diamond_dag_is_supported():
    levels = validate_plan(
        [
            step("T-001"),
            step("T-002", "T-001"),
            step("T-003", "T-001"),
            step("T-004", "T-002", "T-003"),
        ],
        limits(),
    )
    assert [[s.task_key for s in level] for level in levels] == [
        ["T-001"],
        ["T-002", "T-003"],
        ["T-004"],
    ]


def test_cycle_is_rejected():
    with pytest.raises(PlanValidationError, match="循环依赖"):
        validate_plan([step("T-001", "T-002"), step("T-002", "T-001")], limits())


def test_self_dependency_is_rejected():
    with pytest.raises(PlanValidationError, match="依赖了自己"):
        validate_plan([step("T-001", "T-001")], limits())


def test_missing_dependency_is_rejected():
    with pytest.raises(PlanValidationError, match="不存在的任务"):
        validate_plan([step("T-001", "T-999")], limits())


def test_duplicate_task_key_is_rejected():
    with pytest.raises(PlanValidationError, match="重复"):
        validate_plan([step("T-001"), step("T-001")], limits())


def test_empty_plan_is_rejected():
    with pytest.raises(PlanValidationError, match="计划为空"):
        validate_plan([], limits())


def test_too_many_steps_is_rejected():
    steps = [step(f"T-{i:03d}") for i in range(1, 5)]
    with pytest.raises(PlanValidationError, match="任务数"):
        validate_plan(steps, limits(max_steps=3))


def test_too_deep_is_rejected():
    steps = [step("T-001"), step("T-002", "T-001"), step("T-003", "T-002")]
    with pytest.raises(PlanValidationError, match="深度"):
        validate_plan(steps, limits(max_depth=2))


def test_too_wide_is_rejected():
    steps = [step("T-001"), step("T-002"), step("T-003")]
    with pytest.raises(PlanValidationError, match="单层并发"):
        validate_plan(steps, limits(max_parallel=2))


def test_topological_levels_can_be_called_directly():
    levels = topological_levels([step("B", "A"), step("A")])
    assert [[s.task_key for s in level] for level in levels] == [["A"], ["B"]]
