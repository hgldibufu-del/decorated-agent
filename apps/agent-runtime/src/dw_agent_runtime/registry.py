"""三大注册中心 —— 需求文档 §6。

设计要点：
* **注册中心是事实，不是配置常量**：Supervisor 只允许从 Registry 里选合法 Agent/Skill/Tool，
  所以这里从数据库加载并冻结成不可变 `Spec`（`frozen=True`），后续校验才有意义；
* **一致性校验在加载后、执行前**：Agent 声明的 skill 必须真的属于它，
  Skill 声明的 tool 必须真的被允许 —— 否则 DAG 规划会选到不存在的组合；
* Scope 用字符串保存，校验时与 `UserIdentity.permissions` 比对。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dw_domain.errors import EntityNotFoundError, RegistryValidationError, ToolUnavailableError
from dw_domain.models.agent_runtime import Agent, Skill, Tool
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import UserIdentity
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    agent_type: AgentType
    description: str
    version: str
    supported_skills: tuple[str, ...]
    required_scopes: tuple[str, ...]
    enabled: bool

    @classmethod
    def from_model(cls, model: Agent) -> AgentSpec:
        return cls(
            agent_id=model.agent_id,
            agent_type=AgentType(model.agent_type),
            description=model.description,
            version=model.version,
            supported_skills=tuple(model.supported_skills or ()),
            required_scopes=tuple(model.required_scopes or ()),
            enabled=model.enabled,
        )


@dataclass(frozen=True, slots=True)
class SkillSpec:
    skill_id: str
    agent_type: AgentType
    version: str
    required_scopes: tuple[str, ...]
    risk_level: RiskLevel
    allowed_tools: tuple[str, ...]
    enabled: bool

    @classmethod
    def from_model(cls, model: Skill) -> SkillSpec:
        return cls(
            skill_id=model.skill_id,
            agent_type=AgentType(model.agent_type),
            version=model.version,
            required_scopes=tuple(model.required_scopes or ()),
            risk_level=RiskLevel(model.risk_level),
            allowed_tools=tuple(model.allowed_tools or ()),
            enabled=model.enabled,
        )


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_id: str
    description: str
    required_scopes: tuple[str, ...]
    risk_level: RiskLevel
    timeout_ms: int
    retry_max_attempts: int
    retry_backoff_ms: int
    fallback_tool_id: str | None
    idempotency_required: bool
    audit_required: bool
    enabled: bool

    @classmethod
    def from_model(cls, model: Tool) -> ToolSpec:
        return cls(
            tool_id=model.tool_id,
            description=model.description,
            required_scopes=tuple(model.required_scopes or ()),
            risk_level=RiskLevel(model.risk_level),
            timeout_ms=model.timeout_ms,
            retry_max_attempts=model.retry_max_attempts,
            retry_backoff_ms=model.retry_backoff_ms,
            fallback_tool_id=model.fallback_tool_id,
            idempotency_required=model.idempotency_required,
            audit_required=model.audit_required,
            enabled=model.enabled,
        )


class AgentRegistry:
    def __init__(self, specs: Sequence[AgentSpec]) -> None:
        self._by_id = {spec.agent_id: spec for spec in specs if spec.enabled}

    def all(self) -> list[AgentSpec]:
        return list(self._by_id.values())

    def get(self, agent_id: str) -> AgentSpec | None:
        return self._by_id.get(agent_id)

    def require(self, agent_id: str) -> AgentSpec:
        spec = self.get(agent_id)
        if spec is None:
            raise EntityNotFoundError(f"Agent 未注册或未启用: {agent_id}")
        return spec

    def supports_skill(self, agent_id: str, skill_id: str) -> bool:
        spec = self.get(agent_id)
        return spec is not None and skill_id in spec.supported_skills


class SkillRegistry:
    def __init__(self, specs: Sequence[SkillSpec]) -> None:
        self._by_id = {spec.skill_id: spec for spec in specs if spec.enabled}

    def all(self) -> list[SkillSpec]:
        return list(self._by_id.values())

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._by_id.get(skill_id)

    def require(self, skill_id: str) -> SkillSpec:
        spec = self.get(skill_id)
        if spec is None:
            raise EntityNotFoundError(f"Skill 未注册或未启用: {skill_id}")
        return spec

    def allows_tool(self, skill_id: str, tool_id: str) -> bool:
        spec = self.get(skill_id)
        return spec is not None and tool_id in spec.allowed_tools


class ToolRegistry:
    def __init__(self, specs: Sequence[ToolSpec]) -> None:
        self._by_id = {spec.tool_id: spec for spec in specs if spec.enabled}

    def all(self) -> list[ToolSpec]:
        return list(self._by_id.values())

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._by_id.get(tool_id)

    def require(self, tool_id: str) -> ToolSpec:
        spec = self.get(tool_id)
        if spec is None:
            # 未注册 / 已禁用对调用方是「工具不可用」，而不是 404 资源不存在
            raise ToolUnavailableError(f"Tool 未注册或未启用: {tool_id}")
        return spec


@dataclass(frozen=True, slots=True)
class RuntimeRegistries:
    agents: AgentRegistry
    skills: SkillRegistry
    tools: ToolRegistry

    @classmethod
    async def load(cls, session: AsyncSession) -> RuntimeRegistries:
        repository = RegistryRepository(session)
        return cls(
            agents=AgentRegistry([AgentSpec.from_model(m) for m in await repository.list_agents()]),
            skills=SkillRegistry([SkillSpec.from_model(m) for m in await repository.list_skills()]),
            tools=ToolRegistry([ToolSpec.from_model(m) for m in await repository.list_tools()]),
        )

    def validate_task(self, agent_id: str, skill_id: str, tool_ids: Sequence[str] = ()) -> None:
        """规划阶段的合法性校验：Agent 是否支持该 Skill，Skill 是否允许这些 Tool。"""
        agent = self.agents.require(agent_id)
        skill = self.skills.require(skill_id)

        if skill.skill_id not in agent.supported_skills:
            raise RegistryValidationError(f"Agent {agent_id} 不支持 Skill {skill_id}")
        if skill.agent_type is not agent.agent_type:
            raise RegistryValidationError(
                f"Skill {skill_id} 属于 {skill.agent_type.value}，"
                f"与 Agent {agent_id}（{agent.agent_type.value}）不匹配"
            )
        for tool_id in tool_ids:
            if tool_id not in skill.allowed_tools:
                raise RegistryValidationError(f"Skill {skill_id} 不允许调用 Tool {tool_id}")
            self.tools.require(tool_id)


def missing_scopes(actor: UserIdentity, required: Sequence[str]) -> list[str]:
    """返回调用方缺失的 scope；admin 视为拥有一切。"""
    if actor.is_admin:
        return []
    granted = {permission.value for permission in actor.permissions}
    return [scope for scope in required if scope not in granted]
