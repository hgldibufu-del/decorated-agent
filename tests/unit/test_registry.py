"""注册中心纯逻辑单测（不连数据库）。"""

from __future__ import annotations

import pytest
from dw_agent_runtime.registry import (
    AgentRegistry,
    AgentSpec,
    SkillRegistry,
    SkillSpec,
    ToolRegistry,
    ToolSpec,
    missing_scopes,
)
from dw_domain.errors import EntityNotFoundError, RegistryValidationError, ToolUnavailableError
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import PermissionCode, RoleName, UserIdentity


def agent_spec(
    agent_id: str = "aftersales_agent",
    agent_type: AgentType = AgentType.AFTERSALES,
    skills: tuple[str, ...] = ("ticket_triage",),
    scopes: tuple[str, ...] = ("aftersales:read",),
    enabled: bool = True,
) -> AgentSpec:
    return AgentSpec(
        agent_id=agent_id,
        agent_type=agent_type,
        description="售后 Agent",
        version="0.1.0",
        supported_skills=skills,
        required_scopes=scopes,
        enabled=enabled,
    )


def skill_spec(
    skill_id: str = "ticket_triage",
    agent_type: AgentType = AgentType.AFTERSALES,
    tools: tuple[str, ...] = ("ticket_query",),
    risk: RiskLevel = RiskLevel.L1,
    enabled: bool = True,
) -> SkillSpec:
    return SkillSpec(
        skill_id=skill_id,
        agent_type=agent_type,
        version="0.1.0",
        required_scopes=("aftersales:read",),
        risk_level=risk,
        allowed_tools=tools,
        enabled=enabled,
    )


def tool_spec(tool_id: str = "ticket_query", enabled: bool = True) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description="查询工单",
        required_scopes=("aftersales:read",),
        risk_level=RiskLevel.L1,
        timeout_ms=3000,
        retry_max_attempts=2,
        retry_backoff_ms=100,
        fallback_tool_id=None,
        idempotency_required=False,
        audit_required=True,
        enabled=enabled,
    )


def registries():
    from dw_agent_runtime.registry import RuntimeRegistries

    return RuntimeRegistries(
        agents=AgentRegistry([agent_spec()]),
        # 第二个技能已注册但不在 Agent 支持列表里，用于验证「不支持」分支
        skills=SkillRegistry([skill_spec(), skill_spec(skill_id="root_cause")]),
        tools=ToolRegistry([tool_spec()]),
    )


def identity(permissions: list[PermissionCode], admin: bool = False) -> UserIdentity:
    from uuid import uuid4

    return UserIdentity(
        user_id=uuid4(),
        email="u@dw.local",
        full_name="u",
        roles=[RoleName.ADMIN] if admin else [RoleName.AFTERSALES],
        permissions=permissions,
    )


# -----------------------------------------------------------------------------
# 查询
# -----------------------------------------------------------------------------
def test_require_returns_registered_agent():
    assert registries().agents.require("aftersales_agent").agent_id == "aftersales_agent"


def test_unknown_agent_raises_not_found():
    with pytest.raises(EntityNotFoundError):
        registries().agents.require("nope")


def test_unknown_tool_raises_unavailable_instead_of_not_found():
    """工具不存在对调用方是「能力不可用」(503)，不是「资源不存在」(404)。"""
    with pytest.raises(ToolUnavailableError):
        registries().tools.require("nope")


def test_disabled_entries_are_not_selectable():
    registry = ToolRegistry([tool_spec(enabled=False)])
    assert registry.get("ticket_query") is None
    with pytest.raises(ToolUnavailableError):
        registry.require("ticket_query")


def test_supports_skill_and_allows_tool():
    runtime = registries()
    assert runtime.agents.supports_skill("aftersales_agent", "ticket_triage") is True
    assert runtime.agents.supports_skill("aftersales_agent", "budget_estimate") is False
    assert runtime.skills.allows_tool("ticket_triage", "ticket_query") is True
    assert runtime.skills.allows_tool("ticket_triage", "calculate_quote") is False


# -----------------------------------------------------------------------------
# 组合校验
# -----------------------------------------------------------------------------
def test_validate_task_accepts_consistent_combination():
    registries().validate_task("aftersales_agent", "ticket_triage", ["ticket_query"])


def test_validate_task_rejects_unsupported_skill():
    with pytest.raises(RegistryValidationError, match="不支持"):
        registries().validate_task("aftersales_agent", "root_cause")


def test_validate_task_rejects_agent_type_mismatch():
    """技能挂在 Agent 的支持列表里，但 agent_type 不一致 —— 必须被拦下。"""
    from dw_agent_runtime.registry import RuntimeRegistries

    runtime = RuntimeRegistries(
        agents=AgentRegistry([agent_spec()]),
        skills=SkillRegistry([skill_spec(agent_type=AgentType.QUOTE)]),
        tools=ToolRegistry([tool_spec()]),
    )
    with pytest.raises(RegistryValidationError, match="不匹配"):
        runtime.validate_task("aftersales_agent", "ticket_triage")


def test_validate_task_rejects_tool_outside_allowlist():
    with pytest.raises(RegistryValidationError, match="不允许"):
        registries().validate_task("aftersales_agent", "ticket_triage", ["calculate_quote"])


# -----------------------------------------------------------------------------
# Scope
# -----------------------------------------------------------------------------
def test_missing_scopes_reports_only_missing_ones():
    actor = identity([PermissionCode.AFTERSALES_READ])
    assert missing_scopes(actor, ["aftersales:read"]) == []
    assert missing_scopes(actor, ["aftersales:read", "aftersales:write"]) == ["aftersales:write"]


def test_admin_has_every_scope():
    assert missing_scopes(identity([], admin=True), ["project:write", "quote:write"]) == []
