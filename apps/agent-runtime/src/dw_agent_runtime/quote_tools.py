"""Quote 工具（业务表驱动，确定性计算）—— Phase 5。

三个工具把报价业务表接到报价估算技能上：
* `budget_estimate`  基于项目面积 + 所选套餐，计算明细与总价（确定性、Decimal 精度）；
* `package_compare`  同一面积下对比多个套餐的总价与每平米单价；
* `material_lookup`  按类目 / 关键词检索工艺 / 材料项。

工具只决定「从业务表取什么数据、怎么算」，金额逻辑由 `skills.run_quote_estimate` 编排。
所有金额以 `Decimal` 计算，对外序列化为字符串，避免 float 舍入（满足 `project.py` 约束）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from dw_agent_runtime.tools import RiskLevel, ToolContext, ToolDefinition
from dw_domain.access_control import AccessSubject, can_read_project
from dw_domain.errors import EntityNotFoundError, ToolPermissionError, ToolValidationError
from dw_domain.models.project import House
from dw_domain.models.quote import QuoteItem, QuotePackage
from dw_domain.repositories.projects import ProjectRepository


# -----------------------------------------------------------------------------
# 纯函数（可单测，不依赖 DB）
# -----------------------------------------------------------------------------
def _compute_estimate(
    area_sqm: Decimal, base_price: Decimal, price_per_sqm: Decimal
) -> tuple[list[dict[str, str]], Decimal]:
    """基础费 + 面积 × 单价 → 明细与总价（均量化到分）。"""
    base = Decimal(str(base_price)).quantize(Decimal("0.01"))
    area_part = (Decimal(str(area_sqm)) * Decimal(str(price_per_sqm))).quantize(Decimal("0.01"))
    total = (base + area_part).quantize(Decimal("0.01"))
    line_items = [
        {"label": "基础服务费", "amount": str(base), "detail": "套餐基础费"},
        {
            "label": "面积计价",
            "amount": str(area_part),
            "detail": f"{area_sqm} m² × {price_per_sqm} 元/m²",
        },
    ]
    return line_items, total


def _rank_packages(area_sqm: Decimal, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一面积下计算每个套餐总价并升序排序。"""
    result: list[dict[str, Any]] = []
    for package in packages:
        base = Decimal(str(package["base_price"]))
        per = Decimal(str(package["price_per_sqm"]))
        total = (base + area_sqm * per).quantize(Decimal("0.01"))
        per_sqm = (
            (total / area_sqm).quantize(Decimal("0.01")) if area_sqm else Decimal("0.00")
        )
        result.append({**package, "total": str(total), "per_sqm_effective": str(per_sqm)})
    result.sort(key=lambda item: Decimal(item["total"]))
    return result


def _match_items(
    items: list[dict[str, Any]],
    category: str | None = None,
    keyword: str = "",
) -> list[dict[str, Any]]:
    """按类目过滤 + 关键词（名称 + 关键词元数据）模糊匹配。"""
    kw = (keyword or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in items:
        if category and item.get("category") != category:
            continue
        metadata = item.get("metadata_json") or {}
        keywords = metadata.get("keywords", []) if isinstance(metadata, dict) else []
        blob = f'{item.get("name", "")} {" ".join(keywords)}'.lower()
        if kw and kw not in blob:
            continue
        out.append(item)
    return out


# -----------------------------------------------------------------------------
# 套餐选择
# -----------------------------------------------------------------------------
async def _select_package(
    session: Any, package_id: UUID | None
) -> QuotePackage:
    if package_id is not None:
        row = (
            await session.execute(select(QuotePackage).where(QuotePackage.id == package_id))
        ).scalar_one_or_none()
        if row is None:
            raise EntityNotFoundError(f"套餐不存在: {package_id}")
        return row

    rows = (await session.execute(select(QuotePackage))).scalars().all()
    if not rows:
        raise ToolValidationError("报价目录为空，无法选择套餐")
    for tier in ("标准", "经济"):
        hit = next((row for row in rows if (row.tier or "") == tier), None)
        if hit is not None:
            return hit
    return sorted(rows, key=lambda row: row.name)[0]


# -----------------------------------------------------------------------------
# budget_estimate
# -----------------------------------------------------------------------------
class BudgetEstimateIn(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


async def _budget_estimate(payload: BudgetEstimateIn, ctx: ToolContext) -> dict[str, Any]:
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
        raise ToolValidationError("该房屋未登记面积，无法估算报价")

    package = await _select_package(ctx.session, payload.package_id)
    line_items, total = _compute_estimate(area, package.base_price, package.price_per_sqm)
    return {
        "project_id": str(project.id),
        "area_sqm": str(area),
        "layout": house.layout,
        "package": {
            "id": str(package.id),
            "name": package.name,
            "tier": package.tier,
            "base_price": str(package.base_price),
            "price_per_sqm": str(package.price_per_sqm),
            "included_scope": package.included_scope,
        },
        "line_items": line_items,
        "total": str(total),
        "currency": "CNY",
        "assumptions": [
            "面积取自项目关联房屋",
            "按所选套餐的「基础费 + 面积×单价」估算，不含个性化增项",
            "最终报价以正式签约单为准",
        ],
        "confidence": 0.85,
    }


# -----------------------------------------------------------------------------
# package_compare
# -----------------------------------------------------------------------------
class PackageCompareIn(BaseModel):
    area_sqm: Decimal = Field(ge=0)
    packages: list[UUID] | None = None
    requirements: str | None = Field(default=None, max_length=2000)


async def _package_compare(payload: PackageCompareIn, ctx: ToolContext) -> dict[str, Any]:
    stmt = select(QuotePackage)
    if payload.packages:
        stmt = stmt.where(QuotePackage.id.in_(payload.packages))
    rows = (await ctx.session.execute(stmt)).scalars().all()
    packages = [
        {
            "id": str(row.id),
            "name": row.name,
            "tier": row.tier,
            "base_price": str(row.base_price),
            "price_per_sqm": str(row.price_per_sqm),
        }
        for row in rows
    ]
    return {
        "area_sqm": str(payload.area_sqm),
        "packages": _rank_packages(payload.area_sqm, packages),
        "currency": "CNY",
    }


# -----------------------------------------------------------------------------
# material_lookup
# -----------------------------------------------------------------------------
class MaterialLookupIn(BaseModel):
    category: str | None = Field(default=None, max_length=64)
    keyword: str = Field(default="", max_length=200)


async def _material_lookup(payload: MaterialLookupIn, ctx: ToolContext) -> dict[str, Any]:
    stmt = select(QuoteItem)
    if payload.category:
        stmt = stmt.where(QuoteItem.category == payload.category)
    rows = (await ctx.session.execute(stmt)).scalars().all()
    items = [
        {
            "id": str(row.id),
            "category": row.category,
            "name": row.name,
            "unit": row.unit,
            "unit_price": str(row.unit_price),
            "metadata_json": row.metadata_json,
        }
        for row in rows
    ]
    return {
        "query": {"category": payload.category, "keyword": payload.keyword},
        "items": _match_items(items, payload.category, payload.keyword),
    }


# -----------------------------------------------------------------------------
# 注册表
# -----------------------------------------------------------------------------
QUOTE_TOOLS: dict[str, ToolDefinition[Any]] = {
    "budget_estimate": ToolDefinition(
        tool_id="budget_estimate",
        description="基于项目面积与所选套餐计算报价明细与总价（Decimal 精度）",
        required_scopes=("project:read", "quote:read"),
        risk_level=RiskLevel.L0,
        input_model=BudgetEstimateIn,
        handler=_budget_estimate,
    ),
    "package_compare": ToolDefinition(
        tool_id="package_compare",
        description="同一面积下对比多个套餐总价与每平米单价",
        required_scopes=("project:read", "quote:read"),
        risk_level=RiskLevel.L0,
        input_model=PackageCompareIn,
        handler=_package_compare,
    ),
    "material_lookup": ToolDefinition(
        tool_id="material_lookup",
        description="按类目 / 关键词检索工艺与材料项及单价",
        required_scopes=("project:read", "quote:read"),
        risk_level=RiskLevel.L0,
        input_model=MaterialLookupIn,
        handler=_material_lookup,
    ),
}
