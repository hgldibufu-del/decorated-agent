"""Agent 基础设施仓储 —— 需求文档 §6 / §8 / §22。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from dw_schemas.agent import (
    ApprovalStatus,
    RiskLevel,
    RunMode,
    RunStatus,
    ToolCallStatus,
)
from sqlalchemy import select

from dw_domain.models.agent_runtime import (
    Agent,
    AgentRun,
    AgentTask,
    Approval,
    Artifact,
    AuditLog,
    Checkpoint,
    Skill,
    Tool,
    ToolCall,
)
from dw_domain.repositories.base import SqlAlchemyRepository


class RegistryRepository(SqlAlchemyRepository):
    """注册中心读写。ensure_* 幂等，供 seed 与测试重复执行。"""

    async def list_agents(self, *, enabled_only: bool = True) -> Sequence[Agent]:
        stmt = select(Agent).order_by(Agent.agent_id)
        if enabled_only:
            stmt = stmt.where(Agent.enabled.is_(True))
        return (await self._session.execute(stmt)).unique().scalars().all()

    async def list_skills(self, *, enabled_only: bool = True) -> Sequence[Skill]:
        stmt = select(Skill).order_by(Skill.skill_id)
        if enabled_only:
            stmt = stmt.where(Skill.enabled.is_(True))
        return (await self._session.execute(stmt)).unique().scalars().all()

    async def list_tools(self, *, enabled_only: bool = True) -> Sequence[Tool]:
        stmt = select(Tool).order_by(Tool.tool_id)
        if enabled_only:
            stmt = stmt.where(Tool.enabled.is_(True))
        return (await self._session.execute(stmt)).unique().scalars().all()

    async def get_agent(self, agent_id: str) -> Agent | None:
        return (
            (await self._session.execute(select(Agent).where(Agent.agent_id == agent_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def get_skill(self, skill_id: str) -> Skill | None:
        return (
            (await self._session.execute(select(Skill).where(Skill.skill_id == skill_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def get_tool(self, tool_id: str) -> Tool | None:
        return (
            (await self._session.execute(select(Tool).where(Tool.tool_id == tool_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def ensure_agent(
        self,
        *,
        agent_id: str,
        agent_type: str,
        description: str,
        version: str,
        supported_skills: list[str],
        required_scopes: list[str],
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> Agent:
        existing = await self.get_agent(agent_id)
        if existing is not None:
            existing.supported_skills = list(supported_skills)
            existing.required_scopes = list(required_scopes)
            existing.description = description
            existing.version = version
            existing.enabled = enabled
            await self._session.flush()
            return existing
        agent = Agent(
            agent_id=agent_id,
            agent_type=agent_type,
            description=description,
            version=version,
            supported_skills=list(supported_skills),
            required_scopes=list(required_scopes),
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            enabled=enabled,
        )
        self._session.add(agent)
        await self.flush_or_raise_duplicate(field="agent_id", value=agent_id)
        return agent

    async def ensure_skill(
        self,
        *,
        skill_id: str,
        agent_type: str,
        version: str,
        required_scopes: list[str],
        risk_level: RiskLevel,
        allowed_tools: list[str],
        enabled: bool = True,
    ) -> Skill:
        existing = await self.get_skill(skill_id)
        if existing is not None:
            existing.allowed_tools = list(allowed_tools)
            existing.required_scopes = list(required_scopes)
            existing.risk_level = risk_level.value
            existing.version = version
            existing.enabled = enabled
            await self._session.flush()
            return existing
        skill = Skill(
            skill_id=skill_id,
            agent_type=agent_type,
            version=version,
            required_scopes=list(required_scopes),
            risk_level=risk_level.value,
            allowed_tools=list(allowed_tools),
        )
        self._session.add(skill)
        await self.flush_or_raise_duplicate(field="skill_id", value=skill_id)
        return skill

    async def ensure_tool(
        self,
        *,
        tool_id: str,
        description: str,
        required_scopes: list[str],
        risk_level: RiskLevel,
        timeout_ms: int = 5000,
        retry_max_attempts: int = 1,
        retry_backoff_ms: int = 200,
        fallback_tool_id: str | None = None,
        idempotency_required: bool = False,
        audit_required: bool = True,
        enabled: bool = True,
    ) -> Tool:
        existing = await self.get_tool(tool_id)
        if existing is not None:
            existing.description = description
            existing.required_scopes = list(required_scopes)
            existing.risk_level = risk_level.value
            existing.timeout_ms = timeout_ms
            existing.retry_max_attempts = retry_max_attempts
            existing.retry_backoff_ms = retry_backoff_ms
            existing.fallback_tool_id = fallback_tool_id
            existing.idempotency_required = idempotency_required
            existing.audit_required = audit_required
            existing.enabled = enabled
            await self._session.flush()
            return existing
        tool = Tool(
            tool_id=tool_id,
            description=description,
            required_scopes=list(required_scopes),
            risk_level=risk_level.value,
            timeout_ms=timeout_ms,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_ms=retry_backoff_ms,
            fallback_tool_id=fallback_tool_id,
            idempotency_required=idempotency_required,
            audit_required=audit_required,
            enabled=enabled,
        )
        self._session.add(tool)
        await self.flush_or_raise_duplicate(field="tool_id", value=tool_id)
        return tool


class RunRepository(SqlAlchemyRepository):
    # ------------------------------------------------------------------ 写
    async def create_run(
        self,
        *,
        objective: str,
        requester_id: UUID | None,
        project_id: UUID | None = None,
        mode: RunMode = RunMode.DIRECT,
        status: RunStatus = RunStatus.PENDING,
    ) -> AgentRun:
        run = AgentRun(
            objective=objective,
            requester_id=requester_id,
            project_id=project_id,
            mode=mode.value,
            status=status.value,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def create_task(self, **fields: Any) -> AgentTask:
        task = AgentTask(**fields)
        self._session.add(task)
        await self._session.flush()
        return task

    async def create_artifact(
        self,
        *,
        run_id: UUID,
        task_id: UUID | None,
        artifact_type: str,
        producer: str,
        payload: dict[str, Any],
    ) -> Artifact:
        # 版本按 (run_id, task_id) 独立递增：并发任务各算各的，互不影响，
        # 不会因共享 artifact_type 而撞 uq_artifacts_run_id_task_id_version。
        existing_version = (
            await self._session.execute(
                select(Artifact.version)
                .where(Artifact.run_id == run_id, Artifact.task_id == task_id)
                .order_by(Artifact.version.desc())
            )
        ).first()
        version = (existing_version[0] if existing_version else 0) + 1
        artifact = Artifact(
            run_id=run_id,
            task_id=task_id,
            artifact_type=artifact_type,
            producer=producer,
            payload=payload,
            version=version,
        )
        self._session.add(artifact)
        await self._session.flush()
        return artifact

    async def create_tool_call(self, **fields: Any) -> ToolCall:
        call = ToolCall(**fields)
        self._session.add(call)
        await self._session.flush()
        return call

    async def create_approval(self, *, run_id: UUID, task_id: UUID | None, reason: str) -> Approval:
        approval = Approval(
            run_id=run_id,
            task_id=task_id,
            reason=reason,
            status=ApprovalStatus.PENDING.value,
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    # ------------------------------------------------------------------ 读
    async def get_run(self, run_id: UUID) -> AgentRun | None:
        return (
            (await self._session.execute(select(AgentRun).where(AgentRun.id == run_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def list_tasks(self, run_id: UUID) -> Sequence[AgentTask]:
        return (
            (
                await self._session.execute(
                    select(AgentTask)
                    .where(AgentTask.run_id == run_id)
                    .order_by(AgentTask.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    async def list_artifacts(self, run_id: UUID) -> Sequence[Artifact]:
        return (
            (
                await self._session.execute(
                    select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    async def list_tool_calls(self, run_id: UUID) -> Sequence[ToolCall]:
        return (
            (
                await self._session.execute(
                    select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        return (
            (await self._session.execute(select(Artifact).where(Artifact.id == artifact_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def find_successful_call(self, idempotency_key: str) -> ToolCall | None:
        return (
            (
                await self._session.execute(
                    select(ToolCall).where(
                        ToolCall.idempotency_key == idempotency_key,
                        ToolCall.status == ToolCallStatus.SUCCESS.value,
                    )
                )
            )
            .unique()
            .scalar_one_or_none()
        )

    async def get_approval(self, approval_id: UUID) -> Approval | None:
        return (
            (await self._session.execute(select(Approval).where(Approval.id == approval_id)))
            .unique()
            .scalar_one_or_none()
        )

    async def list_approvals(self, run_id: UUID) -> Sequence[Approval]:
        return (
            (
                await self._session.execute(
                    select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    async def list_for_requester(
        self, user_id: UUID, *, is_admin: bool, limit: int = 20
    ) -> Sequence[AgentRun]:
        """按发起人收敛的最近 Run（admin 见全部）。

        与 `ProjectRepository.list_for_user` 同思路：**非 admin 只能看到自己发起的 Run**——
        Run 里可能含客户报价等敏感信息，越权即不可见。
        """
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        if not is_admin:
            stmt = stmt.where(AgentRun.requester_id == user_id)
        return (await self._session.execute(stmt)).unique().scalars().all()


class CheckpointRepository(SqlAlchemyRepository):
    """§9 节点级检查点。同一节点的重试会写入新版本，而不是覆盖历史。"""

    async def save(self, *, run_id: UUID, node: str, state: dict[str, Any]) -> Checkpoint:
        latest = (
            await self._session.execute(
                select(Checkpoint.version)
                .where(Checkpoint.run_id == run_id, Checkpoint.node == node)
                .order_by(Checkpoint.version.desc())
            )
        ).first()
        version = (latest[0] if latest else 0) + 1
        checkpoint = Checkpoint(run_id=run_id, node=node, version=version, state=state)
        self._session.add(checkpoint)
        await self._session.flush()
        return checkpoint

    async def latest(self, run_id: UUID) -> Checkpoint | None:
        return (
            (
                await self._session.execute(
                    select(Checkpoint)
                    .where(Checkpoint.run_id == run_id)
                    .order_by(Checkpoint.created_at.desc(), Checkpoint.version.desc())
                )
            )
            .unique()
            .scalar_one_or_none()
        )

    async def list(self, run_id: UUID) -> Sequence[Checkpoint]:
        return (
            (
                await self._session.execute(
                    select(Checkpoint)
                    .where(Checkpoint.run_id == run_id)
                    .order_by(Checkpoint.created_at, Checkpoint.version)
                )
            )
            .unique()
            .scalars()
            .all()
        )


class AuditRepository(SqlAlchemyRepository):
    """§12 审计留痕：每次受治理的操作都要留一条。"""

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_id: UUID | None = None,
        run_id: UUID | None = None,
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            run_id=run_id,
            details=details or {},
        )
        if occurred_at is not None:
            entry.occurred_at = occurred_at
        self._session.add(entry)
        await self._session.flush()
        return entry
