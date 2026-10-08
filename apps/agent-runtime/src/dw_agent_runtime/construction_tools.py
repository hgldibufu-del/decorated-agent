"""Construction 工具（业务表驱动，确定性分析）—— Phase 7。

两个工具把施工业务表接到施工审查技能上：
* `progress_analysis`  按项目施工阶段对比计划 / 实际工期，产出偏差与延期风险；
* `quality_check`      按类目评估验收项，产出加权得分与缺陷清单。

工具只决定「从业务表取什么数据、怎么算」，编排逻辑由 `skills.run_construction_review` 负责。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from dw_agent_runtime.tools import RiskLevel, ToolContext, ToolDefinition
from dw_domain.access_control import AccessSubject, can_read_project
from dw_domain.errors import EntityNotFoundError, ToolPermissionError
from dw_domain.models.construction import ConstructionMilestone, QualityChecklist
from dw_domain.repositories.projects import ProjectRepository


# -----------------------------------------------------------------------------
# 纯函数（可单测，不依赖 DB）
# -----------------------------------------------------------------------------
def _analyze_progress(milestones: list[dict[str, Any]]) -> dict[str, Any]:
    """按阶段对比计划 / 实际工期，产出偏差、落后阶段与风险标记。

    `actual_days` 为 None 表示该阶段尚未开始（不计入实际工期合计，偏差记为 None）。
    """
    items = sorted(milestones, key=lambda m: (m.get("seq") or 0))
    total_planned = sum(int(m.get("planned_days") or 0) for m in items)
    started = [m for m in items if m.get("actual_days") is not None]
    total_actual = sum(int(m["actual_days"]) for m in started)
    completed = [m for m in items if m.get("status") == "completed"]

    stages: list[dict[str, Any]] = []
    delayed: list[dict[str, Any]] = []
    for m in items:
        planned = int(m.get("planned_days") or 0)
        actual = m.get("actual_days")
        deviation = (int(actual) - planned) if actual is not None else None
        stages.append(
            {
                "stage": m["stage"],
                "planned_days": planned,
                "actual_days": actual,
                "status": m.get("status"),
                "deviation_days": deviation,
            }
        )
        if deviation is not None and deviation > 0:
            delayed.append(
                {"stage": m["stage"], "deviation_days": deviation, "status": m.get("status")}
            )

    delayed.sort(key=lambda d: -d["deviation_days"])
    progress_ratio = round(len(completed) / len(items), 2) if items else 0.0
    return {
        "stages": stages,
        "total_planned_days": total_planned,
        "total_actual_days": total_actual,
        "progress_ratio": progress_ratio,
        "delayed_stages": delayed,
        "at_risk": bool(delayed),
    }


def _grade_checklist(items: list[dict[str, Any]], failed_items: list[str]) -> dict[str, Any]:
    """按权重对验收项打分；`failed_items` 中的项计为未通过。

    得分 = 通过项权重 / 总权重（0~1）。未提供任何未通过项时视为「未报告缺陷 → 满分」。
    """
    failed = {name.strip() for name in (failed_items or []) if name and name.strip()}
    total_weight = sum(int(i.get("weight") or 0) for i in items) or 1
    passed_weight = sum(int(i.get("weight") or 0) for i in items if i["item"] not in failed)
    score = round(passed_weight / total_weight, 2)
    defects = [
        {
            "category": i.get("category"),
            "item": i["item"],
            "severity": i.get("severity"),
            "weight": int(i.get("weight") or 0),
        }
        for i in items
        if i["item"] in failed
    ]
    return {
        "items": items,
        "total_weight": total_weight,
        "passed_weight": passed_weight,
        "score": score,
        "defects": defects,
        "passed": not failed,
    }


# -----------------------------------------------------------------------------
# progress_analysis
# -----------------------------------------------------------------------------
class ProgressAnalysisIn(BaseModel):
    project_id: UUID


async def _progress_analysis(payload: ProgressAnalysisIn, ctx: ToolContext) -> dict[str, Any]:
    projects = ProjectRepository(ctx.session)
    project, membership = await projects.find_access(payload.project_id, ctx.actor.user_id)
    if project is None:
        raise EntityNotFoundError(f"项目不存在: {payload.project_id}")

    subject = AccessSubject.from_iterable(
        is_admin=ctx.actor.is_admin,
        membership_role=membership,
        permissions=[permission.value for permission in ctx.actor.permissions],
    )
    if not can_read_project(subject):
        raise ToolPermissionError("无权访问该项目")

    rows = (
        await ctx.session.execute(
            select(ConstructionMilestone)
            .where(ConstructionMilestone.project_id == project.id)
            .order_by(ConstructionMilestone.seq)
        )
    ).scalars().all()
    milestones = [
        {
            "stage": row.stage,
            "seq": row.seq,
            "planned_days": row.planned_days,
            "actual_days": row.actual_days,
            "status": row.status,
        }
        for row in rows
    ]
    result = _analyze_progress(milestones)
    return {"project_id": str(project.id), **result}


# -----------------------------------------------------------------------------
# quality_check
# -----------------------------------------------------------------------------
class QualityCheckIn(BaseModel):
    project_id: UUID
    category: str | None = Field(default=None, max_length=64)
    failed_items: list[str] = Field(default_factory=list)


async def _quality_check(payload: QualityCheckIn, ctx: ToolContext) -> dict[str, Any]:
    projects = ProjectRepository(ctx.session)
    project, membership = await projects.find_access(payload.project_id, ctx.actor.user_id)
    if project is None:
        raise EntityNotFoundError(f"项目不存在: {payload.project_id}")

    subject = AccessSubject.from_iterable(
        is_admin=ctx.actor.is_admin,
        membership_role=membership,
        permissions=[permission.value for permission in ctx.actor.permissions],
    )
    if not can_read_project(subject):
        raise ToolPermissionError("无权访问该项目")

    stmt = select(QualityChecklist)
    if payload.category:
        stmt = stmt.where(QualityChecklist.category == payload.category)
    rows = (await ctx.session.execute(stmt)).scalars().all()
    items = [
        {
            "category": row.category,
            "item": row.item,
            "standard": row.standard,
            "weight": row.weight,
            "severity": row.severity,
        }
        for row in rows
    ]
    graded = _grade_checklist(items, payload.failed_items)
    return {"project_id": str(project.id), "category": payload.category, **graded}


# -----------------------------------------------------------------------------
# 注册表
# -----------------------------------------------------------------------------
CONSTRUCTION_TOOLS: dict[str, ToolDefinition[Any]] = {
    "progress_analysis": ToolDefinition(
        tool_id="progress_analysis",
        description="按项目施工阶段对比计划 / 实际工期，产出偏差与延期风险",
        required_scopes=("project:read", "construction:read"),
        risk_level=RiskLevel.L0,
        input_model=ProgressAnalysisIn,
        handler=_progress_analysis,
    ),
    "quality_check": ToolDefinition(
        tool_id="quality_check",
        description="按类目评估验收项，产出加权得分与缺陷清单",
        required_scopes=("project:read", "construction:read"),
        risk_level=RiskLevel.L0,
        input_model=QualityCheckIn,
        handler=_quality_check,
    ),
}
