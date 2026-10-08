"""Design 工具（业务表驱动，确定性计算）—— Phase 6。

两个工具把设计业务表接到设计提案技能上：
* `layout_analysis`  基于项目户型 + 面积，匹配户型模块并产出空间规划建议（确定性）；
* `style_match`      按偏好 / 约束匹配并排序设计风格（确定性打分）。

工具只决定「从业务表取什么数据、怎么算」，编排逻辑由 `skills.run_design_proposal` 负责。
所有动态结构以 JSONB 存取，对外保持可序列化（列表 / 字典）。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from dw_agent_runtime.tools import RiskLevel, ToolContext, ToolDefinition
from dw_domain.access_control import AccessSubject, can_read_project
from dw_domain.errors import EntityNotFoundError, ToolPermissionError, ToolValidationError
from dw_domain.models.design import DesignStyle, LayoutModule
from dw_domain.models.project import House
from dw_domain.repositories.projects import ProjectRepository


# -----------------------------------------------------------------------------
# 纯函数（可单测，不依赖 DB）
# -----------------------------------------------------------------------------
_BASELINE_ROOM_TYPES = ("厨房", "卫生间", "阳台")


def _derive_room_types(layout: str | None) -> list[str]:
    """从户型字符串推导出需要空间建议的房间类型。

    规则：含「室」→ 卧室；含「厅」→ 客厅 + 餐厅；厨/卫/阳 是住宅标配，始终纳入。
    返回空集合表示完全解析不出 → 调用方回退为返回全部模块。
    """
    layout_str = (layout or "").strip()
    types: set[str] = set(_BASELINE_ROOM_TYPES)
    if "室" in layout_str:
        types.add("卧室")
    if "厅" in layout_str:
        types.update(("客厅", "餐厅"))
    return sorted(types)


def _select_modules(modules: list[LayoutModule], layout: str | None) -> list[LayoutModule]:
    derived = set(_derive_room_types(layout))
    matched = [module for module in modules if module.room_type in derived]
    # 完全解析不出户型（derived 仅含住宅标配）时，无法判断空间构成，回退为全部模块；
    # 否则返回命中模块（matched 非空，兜底保证总有空间建议）。
    if derived <= set(_BASELINE_ROOM_TYPES):
        return list(modules)
    return matched or list(modules)


def _serialize_module(module: LayoutModule) -> dict[str, Any]:
    return {
        "room_type": module.room_type,
        "suggested_function": module.suggested_function,
        "design_principle": module.design_principle,
        "recommended_material_category": module.recommended_material_category,
        "notes": module.notes,
    }


def _rank_styles(
    preference: str, styles: list[DesignStyle]
) -> list[dict[str, Any]]:
    """按偏好关键词给风格打分并排序；无偏好时保持原序、score 记为 0。"""
    pref = (preference or "").strip().lower()
    result: list[dict[str, Any]] = []
    for style in styles:
        tags = style.tags or []
        score = 0
        if pref:
            blob = " ".join(
                [
                    style.name or "",
                    style.style_family or "",
                    " ".join(tags),
                    style.description or "",
                ]
            ).lower()
            if pref in blob:
                score += 2
            score += sum(1 for tag in tags if pref in tag.lower())
        result.append(
            {
                "id": str(style.id),
                "name": style.name,
                "style_family": style.style_family,
                "description": style.description,
                "suitable_layouts": style.suitable_layouts or [],
                "palette": style.palette or [],
                "characteristics": style.characteristics or {},
                "tags": tags,
                "score": score,
            }
        )
    if pref:
        result.sort(key=lambda item: (-item["score"], item["name"]))
    return result


# -----------------------------------------------------------------------------
# layout_analysis
# -----------------------------------------------------------------------------
class LayoutAnalysisIn(BaseModel):
    project_id: UUID


async def _layout_analysis(payload: LayoutAnalysisIn, ctx: ToolContext) -> dict[str, Any]:
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

    house = (
        await ctx.session.execute(select(House).where(House.id == project.house_id))
    ).scalar_one()
    area = house.area_sqm
    if area is None:
        raise ToolValidationError("该房屋未登记面积，无法做空间规划分析")

    rows = (await ctx.session.execute(select(LayoutModule))).scalars().all()
    modules = _select_modules(list(rows), house.layout)
    return {
        "project_id": str(project.id),
        "layout": house.layout,
        "area_sqm": str(area),
        "space_suggestions": [_serialize_module(module) for module in modules],
    }


# -----------------------------------------------------------------------------
# style_match
# -----------------------------------------------------------------------------
class StyleMatchIn(BaseModel):
    preference: str = Field(default="", max_length=200)
    constraints: str = Field(default="", max_length=2000)


async def _style_match(payload: StyleMatchIn, ctx: ToolContext) -> dict[str, Any]:
    rows = (await ctx.session.execute(select(DesignStyle))).scalars().all()
    return {
        "preference": payload.preference,
        "constraints": payload.constraints,
        "styles": _rank_styles(payload.preference, list(rows)),
    }


# -----------------------------------------------------------------------------
# 注册表
# -----------------------------------------------------------------------------
DESIGN_TOOLS: dict[str, ToolDefinition[Any]] = {
    "layout_analysis": ToolDefinition(
        tool_id="layout_analysis",
        description="基于项目户型与面积匹配户型模块，产出空间规划建议",
        required_scopes=("project:read", "design:read"),
        risk_level=RiskLevel.L0,
        input_model=LayoutAnalysisIn,
        handler=_layout_analysis,
    ),
    "style_match": ToolDefinition(
        tool_id="style_match",
        description="按偏好 / 约束匹配并排序设计风格目录",
        required_scopes=("project:read", "design:read"),
        risk_level=RiskLevel.L0,
        input_model=StyleMatchIn,
        handler=_style_match,
    ),
}
