"""技能执行体 —— 需求文档 §5 / §34。

技能 = 「决定调用哪些工具、并把结果整理成 Artifact」的一段业务能力封装。
**只有真正实现了执行体的技能才会出现在 `SKILL_RUNNERS`**；
其余 §5 列出的技能（layout_analysis / budget_estimate / ticket_triage …）
随各自 Specialist Agent 的 Phase 落地，不预先注册空壳。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from dw_domain.errors import ToolValidationError
from dw_schemas.iam import UserIdentity
from dw_schemas.memory import MemoryProfile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.executor import ToolExecutor


@dataclass(frozen=True, slots=True)
class SkillContext:
    run_id: UUID
    task_id: UUID
    actor: UserIdentity
    executor: ToolExecutor
    session: AsyncSession
    # Phase 10：长期记忆画像，由 RunService 统一注入。
    # None 表示「无权读取」或「尚无记忆」——技能必须能安全降级，不假设它一定存在。
    memory: MemoryProfile | None = None


# 返回 (artifact_type, payload)
SkillRunner = Callable[[SkillContext, dict], Awaitable[tuple[str, dict]]]


class ProjectSnapshotIn(BaseModel):
    project_id: UUID
    # §34：下游任务只拿到上游的 artifact_id，需要时自己去取，不复制整个上下文
    include_artifact_ids: list[UUID] = Field(default_factory=list)


async def run_project_snapshot(ctx: SkillContext, payload: dict) -> tuple[str, dict]:
    """加载项目上下文（Supervisor 的第一步，§35 的 project context loading）。

    `include_artifact_ids` 由 PlanRunner 注入，用于 Sequential 模式下
    把上游 Artifact 拼进本次上下文。
    """
    try:
        parsed = ProjectSnapshotIn.model_validate(payload)
    except ValidationError as exc:
        problems = exc.errors()
        reason = problems[0]["msg"] if problems else str(exc)
        raise ToolValidationError(f"技能入参校验失败: {reason}") from exc

    result = await ctx.executor.call(
        "project_query",
        {"project_id": str(parsed.project_id)},
        idempotency_key=f"run:{ctx.run_id}:project_query",
    )

    evidence: list[dict] = [
        {"tool_id": result.tool_id, "replayed": result.replayed, "attempt": result.attempt}
    ]

    # Phase 10：有 memory:read 时顺带召回长期偏好（§35 的 context loading）。
    # 以 `ctx.memory is not None` 作为门禁 —— 无权读取时**根本不调用**该工具，
    # 避免「可选个性化」把只读用户（如 VIEWER）的 Run 弄失败。
    memory_items: list[dict] = []
    if ctx.memory is not None:
        recalled = await ctx.executor.call(
            "memory_recall",
            {"limit": 20},
            idempotency_key=f"run:{ctx.run_id}:memory_recall",
        )
        memory_items = recalled.output["items"]
        evidence.append(
            {
                "tool_id": recalled.tool_id,
                "replayed": recalled.replayed,
                "attempt": recalled.attempt,
            }
        )

    upstream: list[dict] = []
    for artifact_id in parsed.include_artifact_ids:
        upstream_result = await ctx.executor.call(
            "artifact_query",
            {"artifact_id": str(artifact_id)},
            idempotency_key=f"run:{ctx.run_id}:artifact:{artifact_id}",
        )
        upstream.append(upstream_result.output)
        evidence.append({"tool_id": upstream_result.tool_id, "attempt": upstream_result.attempt})

    return (
        "project_snapshot",
        {
            "project": result.output,
            "upstream_artifacts": upstream,
            "memory": memory_items,
            "produced_by": "project_snapshot",
            "evidence": evidence,
        },
    )


SKILL_RUNNERS: dict[str, SkillRunner] = {
    "project_snapshot": run_project_snapshot,
}


# ---------------------------------------------------------------------------
# Phase 4：AfterSales 售后诊断
# ---------------------------------------------------------------------------
async def run_aftersales_diagnosis(ctx: SkillContext, payload: dict) -> tuple[str, dict]:
    """售后诊断：检索 RAG 证据 → 根因假设 → 相似历史案例，产出带引用的 Artifact。

    编排三个 RAG 工具（`case_search` / `root_cause` / `case_match`），
    每个工具调用都走完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计）。
    """
    issue = (payload.get("issue") or "").strip()
    if not issue:
        raise ToolValidationError("aftersales_diagnosis 缺少 issue（问题描述）")

    search = await ctx.executor.call("case_search", {"query": issue, "k": 5})
    root_cause = await ctx.executor.call("root_cause", {"issue": issue})
    similar = await ctx.executor.call("case_match", {"issue": issue, "k": 3})

    return (
        "aftersales_diagnosis",
        {
            "issue": issue,
            "hypothesis": root_cause.output["hypothesis"],
            "suggested_actions": root_cause.output["suggested_actions"],
            "confidence": root_cause.output["confidence"],
            "evidence": search.output["chunks"],
            "similar_cases": similar.output["cases"],
            "produced_by": "aftersales_diagnosis",
        },
    )


SKILL_RUNNERS["aftersales_diagnosis"] = run_aftersales_diagnosis


# ---------------------------------------------------------------------------
# Phase 5：Quote 报价估算
# ---------------------------------------------------------------------------
async def run_quote_estimate(ctx: SkillContext, payload: dict) -> tuple[str, dict]:
    """报价估算：预算计算 → 套餐对比 → 材料检索，产出带引用的 Artifact。

    编排三个业务表驱动工具（`budget_estimate` / `package_compare` / `material_lookup`），
    每个工具调用都走完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计）。
    """
    project_id = payload.get("project_id")
    if not project_id:
        raise ToolValidationError("quote_estimate 缺少 project_id")
    try:
        pid = UUID(project_id)
    except (ValueError, AttributeError) as exc:
        raise ToolValidationError("quote_estimate 的 project_id 非法") from exc

    estimate = await ctx.executor.call(
        "budget_estimate",
        {"project_id": str(pid)},
        idempotency_key=f"run:{ctx.run_id}:budget_estimate",
    )
    area = Decimal(estimate.output["area_sqm"])
    comparison = await ctx.executor.call(
        "package_compare",
        {"area_sqm": str(area)},
        idempotency_key=f"run:{ctx.run_id}:package_compare",
    )
    materials = await ctx.executor.call(
        "material_lookup",
        {"category": "硬装", "keyword": ""},
        idempotency_key=f"run:{ctx.run_id}:material_lookup",
    )

    return (
        "quote_estimate",
        {
            "project_id": str(pid),
            "layout": estimate.output.get("layout"),
            "recommended_package": estimate.output["package"],
            "estimate": {
                "line_items": estimate.output["line_items"],
                "total": estimate.output["total"],
                "currency": estimate.output["currency"],
            },
            "comparison": comparison.output["packages"],
            "materials": materials.output["items"],
            "assumptions": estimate.output["assumptions"],
            "confidence": estimate.output["confidence"],
            "produced_by": "quote_estimate",
        },
    )


SKILL_RUNNERS["quote_estimate"] = run_quote_estimate


# ---------------------------------------------------------------------------
# Phase 6：Design 设计提案
# ---------------------------------------------------------------------------
async def run_design_proposal(ctx: SkillContext, payload: dict) -> tuple[str, dict]:
    """设计提案：空间规划分析 → 风格匹配，产出结构化设计提案 Artifact。

    编排两个业务表驱动工具（`layout_analysis` / `style_match`），
    每个工具调用都走完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计）。
    """
    project_id = payload.get("project_id")
    if not project_id:
        raise ToolValidationError("design_proposal 缺少 project_id")
    try:
        pid = UUID(project_id)
    except (ValueError, AttributeError) as exc:
        raise ToolValidationError("design_proposal 的 project_id 非法") from exc

    preference = (payload.get("preference") or "").strip()
    # Phase 10：本次未显式给偏好时，回落到长期记忆 ——
    # 同一句「出一套设计方案」，偏好新中式的用户与偏好北欧的用户会得到不同首位风格
    memory_style: str | None = None
    if not preference and ctx.memory is not None:
        remembered = ctx.memory.value_for("style")
        if isinstance(remembered, str) and remembered:
            preference = remembered
            memory_style = remembered

    layout = await ctx.executor.call(
        "layout_analysis",
        {"project_id": str(pid)},
        idempotency_key=f"run:{ctx.run_id}:layout_analysis",
    )
    styles = await ctx.executor.call(
        "style_match",
        {"preference": preference, "constraints": ""},
        idempotency_key=f"run:{ctx.run_id}:style_match",
    )

    space = layout.output
    matched = styles.output["styles"]
    recommended = matched[0] if matched else None
    suggested_categories = sorted(
        {
            module["recommended_material_category"]
            for module in space.get("space_suggestions", [])
            if module.get("recommended_material_category")
        }
    )

    assumptions = [
        "户型空间分配与风格推荐基于内置设计目录，未做现场量房",
        "色板与材料类目为建议项，最终以签约设计合同为准",
    ]
    if memory_style:
        # provenance：明确标注偏好来自记忆而非本次请求，
        # 避免把「系统猜的偏好」当成「用户说的偏好」
        assumptions.append(f"风格偏好「{memory_style}」取自长期记忆，本次请求未显式给出")

    return (
        "design_proposal",
        {
            "project_id": str(pid),
            "layout": space.get("layout"),
            "area_sqm": space.get("area_sqm"),
            "space_planning": space.get("space_suggestions", []),
            "preference_used": preference,
            "memory_preference": memory_style,
            "recommended_styles": matched[:3],
            "recommended_palette": recommended["palette"] if recommended else [],
            "suggested_material_categories": suggested_categories,
            "assumptions": assumptions,
            "confidence": 0.8,
            "produced_by": "design_proposal",
        },
    )


SKILL_RUNNERS["design_proposal"] = run_design_proposal


# ---------------------------------------------------------------------------
# Phase 7：Construction 施工审查
# ---------------------------------------------------------------------------
async def run_construction_review(ctx: SkillContext, payload: dict) -> tuple[str, dict]:
    """施工审查：进度分析 → 验收评估，产出结构化施工审查 Artifact。

    编排两个业务表驱动工具（`progress_analysis` / `quality_check`），
    每个工具调用都走完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计）。
    """
    project_id = payload.get("project_id")
    if not project_id:
        raise ToolValidationError("construction_review 缺少 project_id")
    try:
        pid = UUID(project_id)
    except (ValueError, AttributeError) as exc:
        raise ToolValidationError("construction_review 的 project_id 非法") from exc

    progress = await ctx.executor.call(
        "progress_analysis",
        {"project_id": str(pid)},
        idempotency_key=f"run:{ctx.run_id}:progress_analysis",
    )
    quality = await ctx.executor.call(
        "quality_check",
        {"project_id": str(pid), "failed_items": []},
        idempotency_key=f"run:{ctx.run_id}:quality_check",
    )

    prog = progress.output
    qual = quality.output
    delayed = prog.get("delayed_stages", [])

    suggestions: list[str] = []
    if prog.get("at_risk"):
        suggestions.append("对落后阶段补充人力或调整工序以压缩工期")
    if not qual.get("passed"):
        suggestions.append("针对验收缺陷项安排整改并复验")
    if not suggestions:
        suggestions.append("进度与验收均正常，按计划推进")

    return (
        "construction_review",
        {
            "project_id": str(pid),
            "progress": {
                "stages": prog.get("stages", []),
                "total_planned_days": prog.get("total_planned_days"),
                "total_actual_days": prog.get("total_actual_days"),
                "progress_ratio": prog.get("progress_ratio"),
                "delayed_stages": delayed,
                "at_risk": prog.get("at_risk"),
            },
            "quality": {
                "items": qual.get("items", []),
                "score": qual.get("score"),
                "defects": qual.get("defects", []),
                "passed": qual.get("passed"),
            },
            "suggestions": suggestions,
            "assumptions": [
                "进度与验收数据来自工程施工记录，未做现场复测",
                "工期偏差以「实际 - 计划」自然日计，正值为延期",
            ],
            "confidence": 0.82,
            "produced_by": "construction_review",
        },
    )


SKILL_RUNNERS["construction_review"] = run_construction_review

