"""Planner 单测：计划生成 + 限额 + 能力缺失的明确报错。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from dw_agent_runtime.registry import (
    AgentRegistry,
    AgentSpec,
    RuntimeRegistries,
    SkillRegistry,
    SkillSpec,
    ToolRegistry,
    ToolSpec,
)
from dw_agent_runtime.supervisor.planner import Planner
from dw_domain.errors import PlanValidationError, UnsupportedIntentError
from dw_schemas.agent import AgentType, RunMode
from dw_schemas.iam import PermissionCode
from dw_schemas.supervisor import (
    IntentResult,
    IntentType,
    PlannerLimits,
)


def registries() -> RuntimeRegistries:
    return RuntimeRegistries(
        agents=AgentRegistry(
            [
                AgentSpec(
                    agent_id="supervisor_agent",
                    agent_type=AgentType.SUPERVISOR,
                    description="supervisor",
                    version="0.1.0",
                    supported_skills=("project_snapshot",),
                    required_scopes=(PermissionCode.PROJECT_READ.value,),
                    enabled=True,
                )
            ]
        ),
        skills=SkillRegistry(
            [
                SkillSpec(
                    skill_id="project_snapshot",
                    agent_type=AgentType.SUPERVISOR,
                    version="0.1.0",
                    required_scopes=(PermissionCode.PROJECT_READ.value,),
                    risk_level="L0",
                    allowed_tools=("project_query", "artifact_query"),
                    enabled=True,
                )
            ]
        ),
        tools=ToolRegistry(
            [
                ToolSpec(
                    tool_id="project_query",
                    description="",
                    required_scopes=(),
                    risk_level="L0",
                    timeout_ms=1000,
                    retry_max_attempts=1,
                    retry_backoff_ms=1,
                    fallback_tool_id=None,
                    idempotency_required=False,
                    audit_required=True,
                    enabled=True,
                ),
                ToolSpec(
                    tool_id="artifact_query",
                    description="",
                    required_scopes=(),
                    risk_level="L0",
                    timeout_ms=1000,
                    retry_max_attempts=1,
                    retry_backoff_ms=1,
                    fallback_tool_id=None,
                    idempotency_required=False,
                    audit_required=True,
                    enabled=True,
                ),
            ]
        ),
    )


def intent(value: IntentType, confidence: float = 0.8) -> IntentResult:
    return IntentResult(intent=value, confidence=confidence)


def test_single_project_produces_direct_plan():
    plan = Planner(registries()).plan(
        intent_result=intent(IntentType.PROJECT_OVERVIEW),
        objective="看概览",
        project_ids=[uuid4()],
    )
    assert plan.mode is RunMode.DIRECT
    assert len(plan.steps) == 1


def test_multiple_projects_produce_parallel_plan_capped_by_max_parallel():
    planner = Planner(registries(), PlannerLimits(max_parallel=2))
    plan = planner.plan(
        intent_result=intent(IntentType.PROJECT_OVERVIEW),
        objective="看全部概览",
        project_ids=[uuid4() for _ in range(5)],
    )
    assert plan.mode is RunMode.PARALLEL_DAG
    assert len(plan.steps) == 2, "并行度必须受 max_parallel 限制"
    assert plan.rationale


def test_compare_produces_sequential_plan_with_dependency():
    plan = Planner(registries()).plan(
        intent_result=intent(IntentType.PROJECT_COMPARE),
        objective="对比两个项目",
        project_ids=[uuid4(), uuid4()],
    )
    assert plan.mode is RunMode.SEQUENTIAL
    assert [step.task_key for step in plan.steps] == ["T-001", "T-002"]
    assert plan.steps[1].depends_on == ["T-001"]


def test_compare_requires_two_projects():
    with pytest.raises(UnsupportedIntentError, match="至少需要 2 个"):
        Planner(registries()).plan(
            intent_result=intent(IntentType.PROJECT_COMPARE),
            objective="对比",
            project_ids=[uuid4()],
        )


def test_overview_without_projects_is_rejected():
    with pytest.raises(UnsupportedIntentError, match="没有可见项目"):
        Planner(registries()).plan(
            intent_result=intent(IntentType.PROJECT_OVERVIEW),
            objective="概览",
            project_ids=[],
        )


def test_unknown_intent_is_rejected_clearly():
    with pytest.raises(UnsupportedIntentError, match="无法识别"):
        Planner(registries()).plan(
            intent_result=IntentResult(intent=IntentType.UNKNOWN),
            objective="嗯",
            project_ids=[uuid4()],
        )


def test_all_domain_intents_are_implemented():
    """Phase 7 后 §5 的四个领域意图全部落地，MISSING 能力提示清空。"""
    from dw_agent_runtime.supervisor.planner import INTENT_CAPABILITY, MISSING_CAPABILITY_HINT

    assert MISSING_CAPABILITY_HINT == {}
    for value in (
        IntentType.AFTERSALES_DIAGNOSIS,
        IntentType.QUOTE_ESTIMATE,
        IntentType.DESIGN_PROPOSAL,
        IntentType.CONSTRUCTION_REVIEW,
    ):
        assert value in INTENT_CAPABILITY


def test_plan_is_validated_against_limits_before_returned():
    """max_parallel=1 时概览计划会自动收敛成单任务，而不是产出非法计划。"""
    planner = Planner(registries(), PlannerLimits(max_parallel=1))
    plan = planner.plan(
        intent_result=intent(IntentType.PROJECT_OVERVIEW),
        objective="概览",
        project_ids=[uuid4(), uuid4()],
    )
    assert len(plan.steps) == 1
    assert plan.mode is RunMode.DIRECT


def test_unregistered_capability_is_reported_not_silently_planned():
    """注册中心里没有对应技能时，Planner 必须报错而不是生成跑不了的步骤。"""
    empty = RuntimeRegistries(
        agents=AgentRegistry([]),
        skills=SkillRegistry([]),
        tools=ToolRegistry([]),
    )
    with pytest.raises(UnsupportedIntentError):
        Planner(empty).plan(
            intent_result=intent(IntentType.PROJECT_OVERVIEW),
            objective="概览",
            project_ids=[uuid4()],
        )


def test_limits_are_inspectable():
    assert PlannerLimits().describe()["max_steps"] == 8
    with pytest.raises(PlanValidationError):
        Planner(registries(), PlannerLimits(max_steps=0)).plan(
            intent_result=intent(IntentType.PROJECT_OVERVIEW),
            objective="概览",
            project_ids=[uuid4()],
        )


def quote_registries() -> RuntimeRegistries:
    return RuntimeRegistries(
        agents=AgentRegistry(
            [
                AgentSpec(
                    agent_id="quote_agent",
                    agent_type=AgentType.QUOTE,
                    description="quote",
                    version="0.1.0",
                    supported_skills=("quote_estimate",),
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.QUOTE_READ.value,
                    ),
                    enabled=True,
                )
            ]
        ),
        skills=SkillRegistry(
            [
                SkillSpec(
                    skill_id="quote_estimate",
                    agent_type=AgentType.QUOTE,
                    version="0.1.0",
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.QUOTE_READ.value,
                    ),
                    risk_level="L0",
                    allowed_tools=("budget_estimate", "package_compare", "material_lookup"),
                    enabled=True,
                )
            ]
        ),
        tools=ToolRegistry(
            [
                ToolSpec(
                    tool_id=tool_id,
                    description="",
                    required_scopes=(),
                    risk_level="L0",
                    timeout_ms=1000,
                    retry_max_attempts=1,
                    retry_backoff_ms=1,
                    fallback_tool_id=None,
                    idempotency_required=False,
                    audit_required=True,
                    enabled=True,
                )
                for tool_id in ("budget_estimate", "package_compare", "material_lookup")
            ]
        ),
    )


def test_quote_estimate_requires_project():
    with pytest.raises(UnsupportedIntentError, match="可见项目"):
        Planner(quote_registries()).plan(
            intent_result=intent(IntentType.QUOTE_ESTIMATE),
            objective="报价",
            project_ids=[],
        )


def test_quote_estimate_produces_direct_plan():
    plan = Planner(quote_registries()).plan(
        intent_result=intent(IntentType.QUOTE_ESTIMATE),
        objective="报价",
        project_ids=[uuid4()],
    )
    assert plan.mode is RunMode.DIRECT
    assert plan.steps[0].skill_id == "quote_estimate"
    assert plan.steps[0].input["project_id"]


def design_registries() -> RuntimeRegistries:
    return RuntimeRegistries(
        agents=AgentRegistry(
            [
                AgentSpec(
                    agent_id="design_agent",
                    agent_type=AgentType.DESIGN,
                    description="design",
                    version="0.1.0",
                    supported_skills=("design_proposal",),
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.DESIGN_READ.value,
                    ),
                    enabled=True,
                )
            ]
        ),
        skills=SkillRegistry(
            [
                SkillSpec(
                    skill_id="design_proposal",
                    agent_type=AgentType.DESIGN,
                    version="0.1.0",
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.DESIGN_READ.value,
                    ),
                    risk_level="L0",
                    allowed_tools=("layout_analysis", "style_match"),
                    enabled=True,
                )
            ]
        ),
        tools=ToolRegistry(
            [
                ToolSpec(
                    tool_id=tool_id,
                    description="",
                    required_scopes=(),
                    risk_level="L0",
                    timeout_ms=1000,
                    retry_max_attempts=1,
                    retry_backoff_ms=1,
                    fallback_tool_id=None,
                    idempotency_required=False,
                    audit_required=True,
                    enabled=True,
                )
                for tool_id in ("layout_analysis", "style_match")
            ]
        ),
    )


def test_design_proposal_requires_project():
    with pytest.raises(UnsupportedIntentError, match="可见项目"):
        Planner(design_registries()).plan(
            intent_result=intent(IntentType.DESIGN_PROPOSAL),
            objective="设计",
            project_ids=[],
        )


def test_design_proposal_produces_direct_plan():
    plan = Planner(design_registries()).plan(
        intent_result=intent(IntentType.DESIGN_PROPOSAL),
        objective="设计",
        project_ids=[uuid4()],
    )
    assert plan.mode is RunMode.DIRECT
    assert plan.steps[0].skill_id == "design_proposal"
    assert plan.steps[0].input["project_id"]


def construction_registries() -> RuntimeRegistries:
    return RuntimeRegistries(
        agents=AgentRegistry(
            [
                AgentSpec(
                    agent_id="construction_agent",
                    agent_type=AgentType.CONSTRUCTION,
                    description="construction",
                    version="0.1.0",
                    supported_skills=("construction_review",),
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.CONSTRUCTION_READ.value,
                    ),
                    enabled=True,
                )
            ]
        ),
        skills=SkillRegistry(
            [
                SkillSpec(
                    skill_id="construction_review",
                    agent_type=AgentType.CONSTRUCTION,
                    version="0.1.0",
                    required_scopes=(
                        PermissionCode.PROJECT_READ.value,
                        PermissionCode.CONSTRUCTION_READ.value,
                    ),
                    risk_level="L0",
                    allowed_tools=("progress_analysis", "quality_check"),
                    enabled=True,
                )
            ]
        ),
        tools=ToolRegistry(
            [
                ToolSpec(
                    tool_id=tool_id,
                    description="",
                    required_scopes=(),
                    risk_level="L0",
                    timeout_ms=1000,
                    retry_max_attempts=1,
                    retry_backoff_ms=1,
                    fallback_tool_id=None,
                    idempotency_required=False,
                    audit_required=True,
                    enabled=True,
                )
                for tool_id in ("progress_analysis", "quality_check")
            ]
        ),
    )


def test_construction_review_requires_project():
    with pytest.raises(UnsupportedIntentError, match="可见项目"):
        Planner(construction_registries()).plan(
            intent_result=intent(IntentType.CONSTRUCTION_REVIEW),
            objective="施工",
            project_ids=[],
        )


def test_construction_review_produces_direct_plan():
    plan = Planner(construction_registries()).plan(
        intent_result=intent(IntentType.CONSTRUCTION_REVIEW),
        objective="施工",
        project_ids=[uuid4()],
    )
    assert plan.mode is RunMode.DIRECT
    assert plan.steps[0].skill_id == "construction_review"
    assert plan.steps[0].input["project_id"]
