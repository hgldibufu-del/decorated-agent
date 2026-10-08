"""Run / Artifact / Approval 接口 —— 需求文档 §8 / §15 / §21 / §34。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from dw_agent_runtime.registry import RuntimeRegistries
from dw_agent_runtime.runs import RunService
from dw_domain.models.agent_runtime import AgentRun
from dw_domain.repositories.agent_runtime import AuditRepository, RunRepository
from dw_schemas.agent import (
    ApprovalDecision,
    ApprovalOut,
    ApprovalStatus,
    ArtifactOut,
    RiskLevel,
    RunCreateRequest,
    RunEvent,
    RunMode,
    RunOut,
    RunStatus,
    TaskOut,
    TaskStatus,
    ToolCallOut,
    ToolCallStatus,
)
from dw_schemas.iam import PermissionCode, UserIdentity
from dw_schemas.supervisor import IntentType, Plan, PlanRequest
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import current_identity, get_db_session, require_permissions
from dw_api.errors import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)

router = APIRouter(tags=["runs"])


async def _run_out(session: AsyncSession, run: AgentRun) -> RunOut:
    repository = RunRepository(session)
    tasks = await repository.list_tasks(run.id)
    artifacts = await repository.list_artifacts(run.id)
    approvals = await repository.list_approvals(run.id)
    return RunOut(
        id=run.id,
        project_id=run.project_id,
        status=RunStatus(run.status),
        mode=RunMode(run.mode),
        objective=run.objective,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        tasks=[
            TaskOut(
                id=task.id,
                task_key=task.task_key,
                agent_id=task.agent_id,
                skill_id=task.skill_id,
                status=TaskStatus(task.status),
                attempt=task.attempt,
                risk_level=RiskLevel(task.risk_level),
                allowed_tools=list(task.allowed_tools or []),
                depends_on=list(task.depends_on or []),
                artifact_id=task.artifact_id,
                error=task.error,
            )
            for task in tasks
        ],
        artifact_ids=[artifact.id for artifact in artifacts],
        approval_id=approvals[-1].id if approvals else None,
        review_decision=run.review_decision,
        review_issues=list(run.review_issues or []),
    )


async def _require_visible_run(
    session: AsyncSession, run_id: UUID, identity: UserIdentity
) -> AgentRun:
    run = await RunRepository(session).get_run(run_id)
    if run is None:
        raise ResourceNotFoundError(f"Run 不存在: {run_id}")
    if not identity.is_admin and str(run.requester_id) != str(identity.user_id):
        # 别人的 Run 里可能含客户报价等敏感信息：无权即不可见
        raise PermissionDeniedError("无权访问该 Run")
    return run


@router.get(
    "/runs",
    response_model=list[RunOut],
    summary="列出当前用户可见的 Run（最近 N 条）",
)
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[RunOut]:
    """按 requester 收敛（admin 见全部）；用于工作台的「运行历史」。"""
    runs = await RunRepository(session).list_for_requester(
        identity.user_id, is_admin=identity.is_admin, limit=limit
    )
    return [await _run_out(session, run) for run in runs]


@router.post(
    "/runs",
    response_model=RunOut,
    status_code=201,
    summary="发起一次 Agent Run（Direct 模式）",
    responses={
        400: {"description": "Agent/Skill 组合或入参不合法"},
        403: {"description": "缺少 skill/agent 所需权限"},
        503: {"description": "技能未实现或工具不可用"},
    },
)
async def create_run(
    payload: RunCreateRequest,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> RunOut:
    registries = await RuntimeRegistries.load(session)
    service = RunService(session, registries=registries)

    if payload.intent:
        try:
            intent = IntentType(payload.intent)
        except ValueError as exc:
            raise ValidationFailedError(f"未知意图: {payload.intent}") from exc
        outcome = await service.execute_intent(
            intent=intent,
            objective=payload.objective,
            actor=identity,
            project_id=payload.project_id,
        )
        return await _run_out(session, outcome.run)

    if not payload.agent_id or not payload.skill_id:
        raise ValidationFailedError("需要同时提供 agent_id 与 skill_id，或提供 intent")

    outcome = await service.execute(
        agent_id=payload.agent_id,
        skill_id=payload.skill_id,
        objective=payload.objective,
        actor=identity,
        project_id=payload.project_id,
        input_payload=payload.input,
    )
    return await _run_out(session, outcome.run)


@router.post("/runs/plan", response_model=Plan, summary="只做规划：返回执行计划，不执行")
async def plan_run(
    payload: PlanRequest,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Plan:
    """自然语言 → 意图 → 受限额约束的 DAG。用于 Workbench 上先给用户看计划。"""
    registries = await RuntimeRegistries.load(session)
    service = RunService(session, registries=registries)
    return await service.preview_plan(
        message=payload.message, actor=identity, project_id=payload.project_id
    )


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunOut,
    summary="从最后一个检查点恢复执行（节点级恢复）",
)
async def resume_run(
    run_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> RunOut:
    registries = await RuntimeRegistries.load(session)
    service = RunService(session, registries=registries)
    outcome = await service.resume(run_id, identity)
    return await _run_out(session, outcome.run)


@router.get("/runs/{run_id}", response_model=RunOut, summary="查询 Run 详情")
async def get_run(
    run_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> RunOut:
    run = await _require_visible_run(session, run_id, identity)
    return await _run_out(session, run)


@router.get(
    "/runs/{run_id}/events",
    response_model=list[RunEvent],
    summary="Run 执行时间线（Task + Tool Call）",
)
async def get_run_events(
    run_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[RunEvent]:
    run = await _require_visible_run(session, run_id, identity)
    repository = RunRepository(session)

    events: list[RunEvent] = [
        RunEvent(kind="run", at=run.created_at, summary=run.objective, status=run.status)
    ]
    for task in await repository.list_tasks(run.id):
        events.append(
            RunEvent(
                kind="task",
                at=task.created_at,
                summary=f"{task.agent_id}.{task.skill_id}",
                status=task.status,
                detail={"task_key": task.task_key, "attempt": task.attempt},
            )
        )
    for call in await repository.list_tool_calls(run.id):
        events.append(
            RunEvent(
                kind="tool_call",
                at=call.created_at,
                summary=call.tool_id,
                status=call.status,
                detail={
                    "attempt": call.attempt,
                    "duration_ms": call.duration_ms,
                    "error": call.error,
                },
            )
        )
    return sorted(events, key=lambda event: event.at)


@router.get(
    "/runs/{run_id}/tool-calls",
    response_model=list[ToolCallOut],
    summary="Run 的工具调用明细（审计用）",
)
async def get_run_tool_calls(
    run_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ToolCallOut]:
    run = await _require_visible_run(session, run_id, identity)
    calls = await RunRepository(session).list_tool_calls(run.id)
    return [
        ToolCallOut(
            id=call.id,
            tool_id=call.tool_id,
            status=ToolCallStatus(call.status),
            attempt=call.attempt,
            duration_ms=call.duration_ms,
            error=call.error,
            created_at=call.created_at,
        )
        for call in calls
    ]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut, summary="读取 Artifact")
async def get_artifact(
    artifact_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ArtifactOut:
    repository = RunRepository(session)
    artifact = await repository.get_artifact(artifact_id)
    if artifact is None:
        raise ResourceNotFoundError(f"Artifact 不存在: {artifact_id}")
    await _require_visible_run(session, artifact.run_id, identity)
    return ArtifactOut(
        id=artifact.id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        producer=artifact.producer,
        payload=artifact.payload,
        version=artifact.version,
        created_at=artifact.created_at,
    )


def _approval_out(approval) -> ApprovalOut:
    return ApprovalOut(
        id=approval.id,
        run_id=approval.run_id,
        task_id=approval.task_id,
        status=ApprovalStatus(approval.status),
        reason=approval.reason,
        created_at=approval.created_at,
        decided_at=approval.decided_at,
    )


async def _decide(
    approval_id: UUID,
    decision: str,
    comment: str | None,
    identity: UserIdentity,
    session: AsyncSession,
) -> ApprovalOut:
    repository = RunRepository(session)
    approval = await repository.get_approval(approval_id)
    if approval is None:
        raise ResourceNotFoundError(f"审批单不存在: {approval_id}")
    await _require_visible_run(session, approval.run_id, identity)
    if approval.status != ApprovalStatus.PENDING.value:
        raise ResourceConflictError(f"审批单已处理: {approval.status}")

    approval.status = (
        ApprovalStatus.APPROVED.value if decision == "approve" else ApprovalStatus.REJECTED.value
    )
    approval.decided_by = identity.user_id
    approval.decided_at = datetime.now(timezone.utc)
    approval.comment = comment

    audit = AuditRepository(session)
    # 注意别写成 approval_{decision}d —— "reject" 会拼成 approval_rejectd
    action = "approval_approved" if decision == "approve" else "approval_rejected"
    await audit.record(
        action=action,
        resource_type="approval",
        resource_id=str(approval.id),
        actor_id=identity.user_id,
        run_id=approval.run_id,
        details={"comment": comment},
    )

    if decision == "reject":
        run = await repository.get_run(approval.run_id)
        if run is not None:
            run.status = RunStatus.FAILED.value
            run.error = "审批被拒绝"
            run.finished_at = approval.decided_at
            tasks = await repository.list_tasks(run.id)
            for task in tasks:
                if task.status == TaskStatus.AWAITING_APPROVAL.value:
                    task.status = TaskStatus.FAILED.value
                    task.error = "审批被拒绝"
        await session.flush()

    return _approval_out(approval)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalOut, summary="通过审批")
async def approve(
    approval_id: UUID,
    body: ApprovalDecision,
    identity: UserIdentity = Depends(require_permissions(PermissionCode.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalOut:
    # 审批后恢复执行依赖 Checkpoint / LangGraph，属于 Phase 3；
    # 这里只完成「决策 + 留痕」这一半职责，不假装已经能续跑。
    return await _decide(approval_id, body.decision, body.comment, identity, session)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalOut, summary="拒绝审批")
async def reject(
    approval_id: UUID,
    body: ApprovalDecision,
    identity: UserIdentity = Depends(require_permissions(PermissionCode.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalOut:
    return await _decide(approval_id, body.decision, body.comment, identity, session)
