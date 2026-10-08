"""RunService —— 需求文档 §7 Direct 模式 / §8 任务契约 / §15 高风险审批。

流程：
    校验 Agent/Skill 组合 → 校验 scope → 建 Run + Task
    → 风险 ≥ L2：建审批并把 Run 置为 awaiting_approval（**不执行**）
    → 否则执行技能 → 产出 Artifact → Run completed

失败处理：Task/Run 落 failed 并写入 error，**再把异常抛出**，
这样 HTTP 层能返回语义正确的状态码（403/400/503），而不是 200 包着失败。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from dw_domain.errors import (
    DomainError,
    EntityNotFoundError,
    InvalidOperationError,
    PermissionDeniedError,
    ToolUnavailableError,
)
from dw_domain.models.agent_runtime import AgentRun, AgentTask, Artifact
from dw_domain.repositories.agent_runtime import AuditRepository, RunRepository
from dw_domain.repositories.projects import ProjectRepository
from dw_schemas.agent import (
    APPROVAL_THRESHOLD,
    ApprovalStatus,
    RunMode,
    RunStatus,
    TaskStatus,
    risk_at_least,
)
from dw_schemas.iam import PermissionCode, UserIdentity
from dw_schemas.memory import MemoryProfile
from dw_schemas.supervisor import (
    IntentResult,
    IntentType,
    Plan,
    PlannerLimits,
    PlanStep,
)
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.registry import RuntimeRegistries, missing_scopes
from dw_agent_runtime.skills import SKILL_RUNNERS, SkillContext
from dw_agent_runtime.supervisor.intent import route
from dw_agent_runtime.supervisor.planner import Planner
from dw_agent_runtime.supervisor.reviewer import (
    RunReviewFacts,
    TaskReviewFact,
    review_run,
)
from dw_agent_runtime.supervisor.runner import PlanRunner, RunnerConfig
from dw_agent_runtime.tools import ToolDefinition
from dw_infrastructure.memory import PostgresMemoryStore, RuleBasedExtractor
from dw_infrastructure.observability import Span, record_error, record_ok, start_span


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run: AgentRun
    artifacts: list[Artifact]
    approval_id: UUID | None = None


def _record_run_outcome(span: Span, outcome: RunOutcome) -> None:
    """把 Run 终态写进 span（在 Run 状态定稿之后调用）。"""
    span.set_attribute("run.id", str(outcome.run.id))
    span.set_attribute("run.status", outcome.run.status)
    span.set_attribute("artifact.count", len(outcome.artifacts))
    if outcome.run.review_decision:
        span.set_attribute("run.review_decision", outcome.run.review_decision)
    if outcome.approval_id:
        span.set_attribute("run.approval_id", str(outcome.approval_id))
    record_ok(span)


def _has_permission(actor: UserIdentity, code: PermissionCode) -> bool:
    """Admin 视为拥有全部权限（与 `dw_api.auth.require_permissions` 的判定一致）。"""
    return actor.is_admin or code in actor.permissions


class RunService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registries: RuntimeRegistries,
        definitions: Mapping[str, ToolDefinition] | None = None,
        limits: PlannerLimits | None = None,
        default_deadline_ms: int = 30_000,
    ) -> None:
        self._session = session
        self._registries = registries
        self._definitions = definitions
        self._limits = limits or PlannerLimits()
        self._default_deadline_ms = default_deadline_ms
        self._runs = RunRepository(session)
        self._audit = AuditRepository(session)

    async def execute(
        self,
        *,
        agent_id: str,
        skill_id: str,
        objective: str,
        actor: UserIdentity,
        project_id: UUID | None = None,
        input_payload: dict | None = None,
    ) -> RunOutcome:
        """直连 Agent/Skill 执行；外包一层 `run.execute` span。"""
        with start_span(
            "run.execute",
            attributes={
                "agent.id": agent_id,
                "skill.id": skill_id,
                "project.id": str(project_id) if project_id else None,
            },
        ) as span:
            try:
                outcome = await self._execute_direct(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    objective=objective,
                    actor=actor,
                    project_id=project_id,
                    input_payload=input_payload,
                )
            except DomainError as exc:
                record_error(span, exc)
                raise
            _record_run_outcome(span, outcome)
            return outcome

    async def _execute_direct(
        self,
        *,
        agent_id: str,
        skill_id: str,
        objective: str,
        actor: UserIdentity,
        project_id: UUID | None = None,
        input_payload: dict | None = None,
    ) -> RunOutcome:
        agent = self._registries.agents.require(agent_id)
        skill = self._registries.skills.require(skill_id)
        self._registries.validate_task(agent.agent_id, skill.skill_id, skill.allowed_tools)

        missing = missing_scopes(actor, list(agent.required_scopes) + list(skill.required_scopes))
        if missing:
            raise PermissionDeniedError(f"缺少权限: {', '.join(missing)}")

        run = await self._runs.create_run(
            objective=objective,
            requester_id=actor.user_id,
            project_id=project_id,
            mode=RunMode.DIRECT,
            status=RunStatus.PENDING,
        )
        task = await self._runs.create_task(
            run_id=run.id,
            task_key="T-001",
            agent_id=agent.agent_id,
            skill_id=skill.skill_id,
            objective=objective,
            input_refs=[],
            allowed_tools=list(skill.allowed_tools),
            risk_level=skill.risk_level.value,
            success_conditions=[],
            deadline_ms=self._default_deadline_ms,
            depends_on=[],
            status=TaskStatus.PENDING.value,
            attempt=0,
            max_retry=0,
        )
        # 直接指定 agent/skill 的请求也落一份单步计划：
        # 否则没有 DAG，就无法从检查点恢复（审批流正是靠它续跑的）
        run.plan = Plan(
            intent=IntentType.DIRECT_REQUEST,
            mode=RunMode.DIRECT,
            steps=[
                PlanStep(
                    task_key="T-001",
                    agent_id=agent.agent_id,
                    skill_id=skill.skill_id,
                    objective=objective,
                    input=dict(input_payload or {}),
                )
            ],
        ).model_dump(mode="json")

        if risk_at_least(skill.risk_level, APPROVAL_THRESHOLD):
            approval = await self._runs.create_approval(
                run_id=run.id,
                task_id=task.id,
                reason=f"技能 {skill.skill_id} 风险等级 {skill.risk_level.value}，需人工审批后执行",
            )
            run.status = RunStatus.AWAITING_APPROVAL.value
            task.status = TaskStatus.AWAITING_APPROVAL.value
            await self._session.flush()
            await self._audit.record(
                action="approval_requested",
                resource_type="approval",
                resource_id=str(approval.id),
                actor_id=actor.user_id,
                run_id=run.id,
                details={"skill_id": skill.skill_id, "risk_level": skill.risk_level.value},
            )
            return RunOutcome(run=run, artifacts=[], approval_id=approval.id)

        runner = SKILL_RUNNERS.get(skill.skill_id)
        if runner is None:
            reason = f"技能未实现执行体: {skill.skill_id}"
            await self._fail(run, task, reason, actor.user_id)
            raise ToolUnavailableError(reason)

        run.status = RunStatus.RUNNING.value
        run.started_at = datetime.now(timezone.utc)
        task.status = TaskStatus.RUNNING.value
        task.attempt = 1
        await self._session.flush()

        # §35：执行前加载长期记忆画像（受 memory:read 约束），随上下文交给技能
        memory = await self._load_memory(actor)

        try:
            executor = ToolExecutor(
                session=self._session,
                tools=self._registries.tools,
                actor=actor,
                run_id=run.id,
                task_id=task.id,
                definitions=self._definitions,
            )
            context = SkillContext(
                run_id=run.id,
                task_id=task.id,
                actor=actor,
                executor=executor,
                session=self._session,
                memory=memory,
            )
            artifact_type, payload = await runner(context, input_payload or {})
            artifact = await self._runs.create_artifact(
                run_id=run.id,
                task_id=task.id,
                artifact_type=artifact_type,
                producer=skill.skill_id,
                payload=payload,
            )
        except DomainError as exc:
            await self._fail(run, task, str(exc), actor.user_id)
            raise
        except Exception as exc:  # 未预期的崩溃：记录后归一化，不吞
            await self._fail(run, task, f"未预期错误: {exc}", actor.user_id)
            raise ToolUnavailableError(f"Run 执行失败: {exc}") from exc

        task.status = TaskStatus.COMPLETED.value
        task.artifact_id = artifact.id
        run.status = RunStatus.COMPLETED.value
        run.finished_at = datetime.now(timezone.utc)
        await self._session.flush()

        await self._audit.record(
            action="run_completed",
            resource_type="agent_run",
            resource_id=str(run.id),
            actor_id=actor.user_id,
            run_id=run.id,
            details={"artifact_id": str(artifact.id), "artifact_type": artifact_type},
        )
        # 执行后学习：从 objective 抽取偏好（受 memory:write 约束，按 kind+key 幂等）
        await self._learn_from_run(run, actor)
        return RunOutcome(run=run, artifacts=[artifact])

    async def _fail(
        self, run: AgentRun, task: AgentTask, reason: str, actor_id: UUID | None
    ) -> None:
        task.status = TaskStatus.FAILED.value
        task.error = reason[:2000]
        run.status = RunStatus.FAILED.value
        run.error = reason[:2000]
        run.finished_at = datetime.now(timezone.utc)
        await self._session.flush()
        await self._audit.record(
            action="run_failed",
            resource_type="agent_run",
            resource_id=str(run.id),
            actor_id=actor_id,
            run_id=run.id,
            details={"reason": reason[:500]},
        )

    # ------------------------------------------------------------------ Phase 3
    async def execute_plan(
        self,
        *,
        intent: IntentType,
        objective: str,
        actor: UserIdentity,
        project_ids: list[UUID],
        confidence: float = 0.0,
    ) -> RunOutcome:
        """按意图执行；外包一层 `run.execute_plan` span（Tool / RAG span 是其子节点）。"""
        with start_span(
            "run.execute_plan",
            attributes={"run.intent": intent.value, "project.count": len(project_ids)},
        ) as span:
            try:
                outcome = await self._execute_plan(
                    intent=intent,
                    objective=objective,
                    actor=actor,
                    project_ids=project_ids,
                    confidence=confidence,
                )
            except DomainError as exc:
                record_error(span, exc)
                raise
            _record_run_outcome(span, outcome)
            return outcome

    async def _execute_plan(
        self,
        *,
        intent: IntentType,
        objective: str,
        actor: UserIdentity,
        project_ids: list[UUID],
        confidence: float = 0.0,
    ) -> RunOutcome:
        """按意图生成计划并执行（Direct / Sequential / Parallel DAG）。"""
        plan = Planner(self._registries, self._limits).plan(
            intent_result=IntentResult(intent=intent, confidence=confidence),
            objective=objective,
            project_ids=project_ids,
        )

        # 执行前校验 Agent/Skill 所需 scope（与 execute() 的直连请求一致）：
        # 缺权限应直接 403，而不是创建一个注定在工具调用阶段失败的 Run。
        first_step = plan.steps[0]
        agent = self._registries.agents.require(first_step.agent_id)
        skill = self._registries.skills.require(first_step.skill_id)
        missing = missing_scopes(
            actor, list(agent.required_scopes) + list(skill.required_scopes)
        )
        if missing:
            raise PermissionDeniedError(f"缺少权限: {', '.join(missing)}")

        run = await self._runs.create_run(
            objective=objective,
            requester_id=actor.user_id,
            project_id=project_ids[0] if project_ids else None,
            mode=plan.mode,
            status=RunStatus.PENDING,
        )
        # 计划必须落库：Checkpoint 恢复时靠它重建 DAG，不能只留在内存
        run.plan = plan.model_dump(mode="json")
        await self._session.flush()

        for step in plan.steps:
            await self._runs.create_task(
                run_id=run.id,
                task_key=step.task_key,
                agent_id=step.agent_id,
                skill_id=step.skill_id,
                objective=step.objective,
                input_refs=list(step.depends_on),
                allowed_tools=[],
                risk_level="L0",
                success_conditions=[],
                deadline_ms=self._limits.deadline_ms,
                depends_on=list(step.depends_on),
                status=TaskStatus.PENDING.value,
                attempt=0,
                max_retry=self._limits.retry_limit,
            )

        run.status = RunStatus.RUNNING.value
        run.started_at = datetime.now(timezone.utc)
        await self._session.flush()

        runner = PlanRunner(
            self._session,
            RunnerConfig(
                registries=self._registries,
                actor=actor,
                limits=self._limits,
                definitions=self._definitions,
                # §35：记忆画像随执行上下文下发，四个 Specialist 自动复用
                memory=await self._load_memory(actor),
            ),
        )
        await runner.execute(run.id, plan)
        return await self._finalize(run.id, actor)

    async def resume(self, run_id: UUID, actor: UserIdentity) -> RunOutcome:
        """恢复执行；外包一层 `run.resume` span（便于把「续跑」与首次执行区分开）。"""
        with start_span("run.resume", attributes={"run.id": str(run_id)}) as span:
            try:
                outcome = await self._resume(run_id, actor)
            except DomainError as exc:
                record_error(span, exc)
                raise
            _record_run_outcome(span, outcome)
            return outcome

    async def _resume(self, run_id: UUID, actor: UserIdentity) -> RunOutcome:
        """从最后一个已完成的节点继续执行（节点级恢复，§9）。"""
        run = await self._runs.get_run(run_id)
        if run is None:
            raise EntityNotFoundError(f"Run 不存在: {run_id}")
        if not actor.is_admin and str(run.requester_id) != str(actor.user_id):
            raise PermissionDeniedError("无权访问该 Run")
        if run.status not in {
            RunStatus.AWAITING_APPROVAL.value,
            RunStatus.FAILED.value,
        }:
            raise InvalidOperationError(f"Run 状态 {run.status} 不可恢复")
        if not run.plan:
            raise InvalidOperationError("Run 没有落库的执行计划，无法恢复")

        plan = Plan.model_validate(run.plan)
        tasks = await self._runs.list_tasks(run.id)
        completed = {
            task.task_key: task.artifact_id
            for task in tasks
            if task.status == TaskStatus.COMPLETED.value and task.artifact_id
        }
        # 审批通过后把等待中的任务放回待执行
        for task in tasks:
            if task.status == TaskStatus.AWAITING_APPROVAL.value:
                task.status = TaskStatus.PENDING.value

        run.status = RunStatus.RUNNING.value
        run.error = None
        await self._session.flush()

        await self._audit.record(
            action="run_resumed",
            resource_type="agent_run",
            resource_id=str(run.id),
            actor_id=actor.user_id,
            run_id=run.id,
            details={"completed_nodes": sorted(completed)},
        )

        runner = PlanRunner(
            self._session,
            RunnerConfig(
                registries=self._registries,
                actor=actor,
                limits=self._limits,
                definitions=self._definitions,
                memory=await self._load_memory(actor),
            ),
        )
        await runner.execute(run.id, plan, completed=completed)
        return await self._finalize(run.id, actor)

    async def execute_intent(
        self,
        *,
        intent: IntentType,
        objective: str,
        actor: UserIdentity,
        project_id: UUID | None = None,
    ) -> RunOutcome:
        """按意图执行：项目范围由调用者可见集决定（Project ACL 继续生效）。"""
        project_ids = await self._visible_project_ids(actor, project_id)
        return await self.execute_plan(
            intent=intent,
            objective=objective,
            actor=actor,
            project_ids=project_ids,
        )

    async def preview_plan(
        self,
        *,
        message: str,
        actor: UserIdentity,
        project_id: UUID | None = None,
    ) -> Plan:
        """自然语言 → 意图 → 计划（不执行），供前端先展示「打算怎么干」。"""
        project_ids = await self._visible_project_ids(actor, project_id)
        return Planner(self._registries, self._limits).plan(
            intent_result=route(message),
            objective=message,
            project_ids=project_ids,
        )

    # ------------------------------------------------------------------ 记忆（Phase 10）
    async def _load_memory(self, actor: UserIdentity) -> MemoryProfile | None:
        """按 `memory:read` 加载用户记忆画像；无权则返回 None（技能自行降级）。

        刻意不抛错：没有记忆权限只是「少一层个性化」，不应让整次 Run 失败。
        """
        if not _has_permission(actor, PermissionCode.MEMORY_READ):
            return None
        items = await PostgresMemoryStore(self._session).recall(actor.user_id)
        return MemoryProfile(user_id=actor.user_id, items=items)

    async def _learn_from_run(self, run: AgentRun, actor: UserIdentity) -> int:
        """从 objective 抽取候选记忆并**幂等**落库（受 `memory:write` 约束）。

        抽取是确定性的规则匹配（`RuleBasedExtractor`）：否定句（「不要新中式」）
        在抽取阶段即被挡掉，因此不会把「不想要」记成「想要」。返回写入条数，便于断言。
        """
        if not _has_permission(actor, PermissionCode.MEMORY_WRITE):
            return 0
        candidates = RuleBasedExtractor().extract(run.objective or "")
        if not candidates:
            return 0
        stored = await PostgresMemoryStore(self._session).remember(
            actor.user_id, candidates, source=f"run:{run.id}"
        )
        return len(stored)

    async def _visible_project_ids(
        self, actor: UserIdentity, project_id: UUID | None
    ) -> list[UUID]:
        if project_id is not None:
            return [project_id]
        rows = await ProjectRepository(self._session).list_for_user(
            actor.user_id, is_admin=actor.is_admin
        )
        return [row[0].id for row in rows]

    async def _finalize(self, run_id: UUID, actor: UserIdentity) -> RunOutcome:
        """执行结束：跑 Reviewer → 定 Run 终态 → 留审计。

        并发任务各自提交过，这里必须重新取 Run，避免操作已过期的 ORM 对象。
        """
        run = await self._runs.get_run(run_id)
        if run is None:  # pragma: no cover - 刚执行完必然存在
            raise EntityNotFoundError(f"Run 不存在: {run_id}")
        tasks = await self._runs.list_tasks(run.id)
        calls = await self._runs.list_tool_calls(run.id)
        approvals = await self._runs.list_approvals(run.id)

        pending_approval = any(
            approval.status == ApprovalStatus.PENDING.value for approval in approvals
        )
        facts = RunReviewFacts(
            tasks=tuple(
                TaskReviewFact(
                    task_key=task.task_key,
                    status=task.status,
                    attempt=task.attempt,
                    has_artifact=task.artifact_id is not None,
                    tool_call_count=sum(1 for call in calls if call.task_id == task.id),
                    denied_calls=sum(
                        1 for call in calls if call.task_id == task.id and call.status == "denied"
                    ),
                    # 仅在「失败且尚未耗尽重试上限」时才算可重试；结构性失败
                    # （如技能没有执行体）attempt 已达上限，必须判 FALLBACK 而非 RETRY。
                    retryable=bool(task.error) and task.attempt < task.max_retry,
                )
                for task in tasks
            ),
            pending_approval=pending_approval,
            retry_limit=self._limits.retry_limit,
        )
        review = review_run(facts)
        run.review_decision = review.decision.value
        run.review_issues = list(review.issues + review.evidence_gaps + review.consistency_issues)
        # 把失败任务的具体错误补进结论：Reviewer 只报告「哪个任务失败」，
        # 真正的原因（如「技能未实现执行体」）在 task.error 里，前端需要它直接展示。
        for task in tasks:
            if task.status == TaskStatus.FAILED.value and task.error:
                run.review_issues.append(task.error[:300])

        now = datetime.now(timezone.utc)
        statuses = {task.status for task in tasks}
        if pending_approval or TaskStatus.AWAITING_APPROVAL.value in statuses:
            run.status = RunStatus.AWAITING_APPROVAL.value
        elif statuses and statuses <= {TaskStatus.COMPLETED.value}:
            run.status = RunStatus.COMPLETED.value
            run.finished_at = now
        else:
            run.status = RunStatus.FAILED.value
            run.finished_at = now
            failed = [task.task_key for task in tasks if task.status != TaskStatus.COMPLETED.value]
            run.error = "失败任务: " + ", ".join(failed)

        await self._session.flush()
        await self._audit.record(
            action="run_reviewed",
            resource_type="agent_run",
            resource_id=str(run.id),
            actor_id=actor.user_id,
            run_id=run.id,
            details={"decision": review.decision.value, "issues": run.review_issues[:5]},
        )

        # 执行后学习：从 objective 抽取偏好（受 memory:write 约束，按 kind+key 幂等）
        await self._learn_from_run(run, actor)

        artifacts = await self._runs.list_artifacts(run.id)
        return RunOutcome(
            run=run,
            artifacts=list(artifacts),
            approval_id=approvals[-1].id if approvals else None,
        )
