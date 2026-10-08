"""PlanRunner —— 需求文档 §7 三种执行模式 + §9 Checkpoint + §15 审批门控。

模式：
* `direct`       单任务
* `sequential`   DAG 只有一条链
* `parallel_dag` 同一层内互不依赖的任务并发执行

**并发安全的关键设计**：SQLAlchemy 的 `AsyncSession` 不是并发安全的，
因此并行层里的每个任务都开自己的会话，只操作自己那一行 Task，
Run/Task 元数据在扇出前先提交（否则并发会话看不到 run 行，外键会失败）。

失败处理（不吞、不假装成功）：
* 可恢复错误（超时 / 下游不可用）在 `retry_limit` 内重试；
* 重试耗尽 → 任务 failed，其下游任务显式标记 skipped；
* 高风险技能 → 建审批单并停在 `awaiting_approval`，已完成节点写入 Checkpoint。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from dw_domain.errors import DomainError, ToolTimeoutError, ToolUnavailableError
from dw_domain.models.agent_runtime import AgentTask
from dw_domain.repositories.agent_runtime import (
    AuditRepository,
    CheckpointRepository,
    RunRepository,
)
from dw_schemas.agent import APPROVAL_THRESHOLD, RunStatus, TaskStatus, risk_at_least
from dw_schemas.iam import UserIdentity
from dw_schemas.memory import MemoryProfile
from dw_schemas.supervisor import Plan, PlannerLimits, PlanStep
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.registry import RuntimeRegistries
from dw_agent_runtime.skills import SKILL_RUNNERS, SkillContext
from dw_agent_runtime.supervisor.dag import validate_plan
from dw_agent_runtime.tools import ToolDefinition

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    task_key: str
    status: str  # completed | failed | awaiting_approval | skipped
    artifact_id: UUID | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    registries: RuntimeRegistries
    actor: UserIdentity
    limits: PlannerLimits
    definitions: Mapping[str, ToolDefinition] | None = None
    # Phase 10：长期记忆画像（None = 无权读取或尚无记忆）
    memory: MemoryProfile | None = None


class PlanRunner:
    def __init__(self, session: AsyncSession, config: RunnerConfig) -> None:
        self._session = session
        self._config = config
        self._runs = RunRepository(session)

    async def execute(
        self,
        run_id: UUID,
        plan: Plan,
        *,
        completed: Mapping[str, UUID] | None = None,
    ) -> list[TaskOutcome]:
        levels = validate_plan(plan.steps, self._config.limits)

        # 并发任务各自开会话，必须让它们能看到 run/task 行 → 先提交一次
        await self._session.commit()

        finished: dict[str, UUID] = dict(completed or {})
        outcomes: list[TaskOutcome] = []
        task_ids = {task.task_key: task.id for task in await self._runs.list_tasks(run_id)}
        # 已审批通过的任务在恢复执行时不应再次要求审批
        approved_tasks = {
            approval.task_id
            for approval in await self._runs.list_approvals(run_id)
            if approval.status == "approved" and approval.task_id is not None
        }

        for level in levels:
            pending = [step for step in level if step.task_key not in finished]
            if not pending:
                continue

            results = await asyncio.gather(
                *(
                    self._run_task(
                        run_id,
                        step,
                        task_ids[step.task_key],
                        finished,
                        task_ids[step.task_key] in approved_tasks,
                    )
                    for step in pending
                )
            )
            outcomes.extend(results)

            for result in results:
                if result.status == "completed" and result.artifact_id:
                    finished[result.task_key] = result.artifact_id

            failed_keys = {
                result.task_key for result in results if result.status in {"failed", "skipped"}
            }
            if any(result.status == "awaiting_approval" for result in results):
                await self._skip_downstream(run_id, plan, failed_keys, task_ids, outcomes)
                break
            if failed_keys:
                await self._skip_downstream(run_id, plan, failed_keys, task_ids, outcomes)
                break

        return outcomes

    # ------------------------------------------------------------------ 单任务
    async def _run_task(
        self,
        run_id: UUID,
        step: PlanStep,
        task_id: UUID,
        finished: Mapping[str, UUID],
        approved: bool = False,
    ) -> TaskOutcome:
        skill = self._config.registries.skills.require(step.skill_id)

        if not approved and risk_at_least(skill.risk_level, APPROVAL_THRESHOLD):
            return await self._request_approval(run_id, step, task_id)

        runner = SKILL_RUNNERS.get(step.skill_id)
        if runner is None:
            return await self._fail_task(run_id, task_id, f"技能未实现执行体: {step.skill_id}")

        payload = {
            **step.input,
            # §34：跨任务只传 artifact_id，由下游自己去取，不复制整个上下文
            "include_artifact_ids": [
                str(finished[dependency])
                for dependency in step.depends_on
                if dependency in finished
            ],
        }

        last_error: DomainError | None = None
        for attempt in range(1, self._config.limits.retry_limit + 2):
            outcome = await self._attempt(run_id, step, task_id, attempt, payload)
            if outcome.status == "completed":
                return outcome
            last_error = DomainError(outcome.error or "任务失败")
            if _is_retryable(last_error) and attempt <= self._config.limits.retry_limit:
                logger.warning(
                    "task retrying", extra={"task_key": step.task_key, "attempt": attempt}
                )
                continue
            return outcome

        return await self._fail_task(
            run_id, task_id, str(last_error) if last_error else "任务未产出结果"
        )

    async def _attempt(
        self,
        run_id: UUID,
        step: PlanStep,
        task_id: UUID,
        attempt: int,
        payload: dict,
    ) -> TaskOutcome:
        """一次尝试：独立会话、独立事务，失败即回滚，不影响其它并发任务。"""
        # 注意：AsyncSession.get_bind() 返回的是「同步引擎孪生体」，不能直接喂给
        # AsyncSession 构造器（会报 AsyncEngine expected）。真正的 AsyncEngine 存在
        # `bind` 属性上，并发任务各自开独立会话、共享同一个引擎连接池。
        # expire_on_commit=False：提交后 PK 等属性仍保留在内存，避免随后访问
        # `artifact.id` 触发「异步会话外的惰性加载」报 MissingGreenlet。
        session = AsyncSession(bind=self._session.bind, expire_on_commit=False)
        try:
            runs = RunRepository(session)
            task = await session.get(AgentTask, task_id)
            if task is None:
                return TaskOutcome(step.task_key, "failed", error="任务行不存在")
            task.status = TaskStatus.RUNNING.value
            task.attempt = attempt
            await session.flush()

            executor = ToolExecutor(
                session=session,
                tools=self._config.registries.tools,
                actor=self._config.actor,
                run_id=run_id,
                task_id=task_id,
                definitions=self._config.definitions,
            )
            context = SkillContext(
                run_id=run_id,
                task_id=task_id,
                actor=self._config.actor,
                executor=executor,
                session=session,
                memory=self._config.memory,
            )

            try:
                artifact_type, artifact_payload = await runner_call(step, context, payload)
            except DomainError as exc:
                await session.rollback()
                reason = str(exc)
                task = await session.get(AgentTask, task_id)
                if task is not None:
                    task.status = TaskStatus.FAILED.value
                    task.error = reason[:2000]
                    await session.commit()
                return TaskOutcome(step.task_key, "failed", error=reason)
            except Exception as exc:  # 记录堆栈后归一化，绝不静默
                logger.exception("task crashed", extra={"task_key": step.task_key})
                await session.rollback()
                task = await session.get(AgentTask, task_id)
                if task is not None:
                    task.status = TaskStatus.FAILED.value
                    task.error = f"未预期错误: {exc}"[:2000]
                    await session.commit()
                return TaskOutcome(step.task_key, "failed", error=f"未预期错误: {exc}")

            artifact = await runs.create_artifact(
                run_id=run_id,
                task_id=task_id,
                artifact_type=artifact_type,
                producer=step.skill_id,
                payload=artifact_payload,
            )
            task.artifact_id = artifact.id
            task.status = TaskStatus.COMPLETED.value
            await CheckpointRepository(session).save(
                run_id=run_id,
                node=step.task_key,
                state={
                    "artifact_id": str(artifact.id),
                    "artifact_type": artifact_type,
                    "attempt": attempt,
                },
            )
            await session.commit()
            return TaskOutcome(step.task_key, "completed", artifact.id)
        finally:
            await session.close()

    async def _request_approval(self, run_id: UUID, step: PlanStep, task_id: UUID) -> TaskOutcome:
        skill = self._config.registries.skills.require(step.skill_id)
        runs = RunRepository(self._session)
        approval = await runs.create_approval(
            run_id=run_id,
            task_id=task_id,
            reason=f"技能 {skill.skill_id} 风险等级 {skill.risk_level.value}，需人工审批",
        )
        task = await self._session.get(AgentTask, task_id)
        if task is not None:
            task.status = TaskStatus.AWAITING_APPROVAL.value
        run = await runs.get_run(run_id)
        if run is not None:
            run.status = RunStatus.AWAITING_APPROVAL.value
        await self._session.flush()
        await AuditRepository(self._session).record(
            action="approval_requested",
            resource_type="approval",
            resource_id=str(approval.id),
            actor_id=self._config.actor.user_id,
            run_id=run_id,
            details={"task_key": step.task_key},
        )
        return TaskOutcome(step.task_key, "awaiting_approval")

    async def _fail_task(self, run_id: UUID, task_id: UUID, reason: str) -> TaskOutcome:
        task = await self._session.get(AgentTask, task_id)
        task_key = task.task_key if task else "?"
        if task is not None:
            task.status = TaskStatus.FAILED.value
            task.error = reason[:2000]
        await self._session.flush()
        await AuditRepository(self._session).record(
            action="task_failed",
            resource_type="agent_task",
            resource_id=str(task_id),
            actor_id=self._config.actor.user_id,
            run_id=run_id,
            details={"task_key": task_key, "reason": reason[:300]},
        )
        return TaskOutcome(task_key, "failed", error=reason)

    async def _skip_downstream(
        self,
        run_id: UUID,
        plan: Plan,
        failed_keys: set[str],
        task_ids: Mapping[str, UUID],
        outcomes: list[TaskOutcome],
    ) -> None:
        """上游失败后，其所有下游必须显式标记 skipped，而不是带着缺失输入继续跑。"""
        to_skip = {step.task_key for step in plan.steps if set(step.depends_on) & failed_keys}
        for step in plan.steps:
            if step.task_key not in to_skip:
                continue
            task = await self._session.get(AgentTask, task_ids[step.task_key])
            if task is not None:
                task.status = TaskStatus.FAILED.value
                task.error = "依赖的上游任务未完成"
            await self._session.flush()
            outcomes.append(TaskOutcome(step.task_key, "skipped", error="依赖的上游任务未完成"))


async def runner_call(step: PlanStep, context: SkillContext, payload: dict):
    """取出技能执行体并调用（抽出来是为了让 except 分支更清晰）。"""
    runner = SKILL_RUNNERS[step.skill_id]
    return await runner(context, payload)


def _is_retryable(error: DomainError) -> bool:
    return isinstance(error, (ToolTimeoutError, ToolUnavailableError))
