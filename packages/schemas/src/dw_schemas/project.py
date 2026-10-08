"""项目域契约 —— 需求文档 §9 / §22（Customer / House / Project / ProjectMember）。

金额统一使用 `Decimal` 并以字符串序列化：报价金额一旦经过 float 就会出现
不可预测的舍入误差，这是装修报价场景不可接受的。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dw_schemas.iam import ProjectRole


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# -----------------------------------------------------------------------------
# Customer
# -----------------------------------------------------------------------------
class CustomerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=64)
    phone: str = Field(..., min_length=5, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class CustomerUpdate(BaseModel):
    """客户部分更新：仅更新显式提供的字段。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str
    email: str | None
    note: str | None
    created_at: datetime


# -----------------------------------------------------------------------------
# House
# -----------------------------------------------------------------------------
class HouseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: UUID
    address: str = Field(..., min_length=2, max_length=255)
    city: str | None = Field(default=None, max_length=64)
    area_sqm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    layout: str | None = Field(default=None, max_length=64, description="户型，如 三室两厅")
    note: str | None = Field(default=None, max_length=2000)


class HouseUpdate(BaseModel):
    """房屋部分更新：仅更新显式提供的字段（不允许改挂到别的客户）。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address: str | None = Field(default=None, min_length=2, max_length=255)
    city: str | None = Field(default=None, max_length=64)
    area_sqm: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    layout: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class HouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    address: str
    city: str | None
    area_sqm: Decimal | None
    layout: str | None
    note: str | None


# -----------------------------------------------------------------------------
# Project
# -----------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=2, max_length=32, description="项目编号，全局唯一")
    name: str = Field(..., min_length=1, max_length=128)
    customer_id: UUID
    house_id: UUID
    status: ProjectStatus = ProjectStatus.DRAFT
    budget_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    planned_start_date: date | None = None
    planned_complete_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    """项目部分更新：仅更新显式提供的字段。

    `version` 是乐观锁令牌：必须回传详情里读到的版本；不匹配即 409（并发编辑保护）。
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    version: int = Field(..., ge=1, description="客户端最后读到的项目版本（乐观锁）")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: ProjectStatus | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    planned_start_date: date | None = None
    planned_complete_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProjectSummary(BaseModel):
    """列表极小返回体：带上当前调用者的成员角色，供前端决定是否展示写操作入口。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    status: ProjectStatus
    customer_name: str
    house_address: str
    member_role: ProjectRole | None = Field(
        default=None, description="当前用户在该项目的角色；admin 无成员关系时为 None"
    )
    created_at: datetime


class ProjectDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    status: ProjectStatus
    customer_id: UUID
    house_id: UUID
    budget_amount: Decimal | None
    planned_start_date: date | None
    planned_complete_date: date | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    customer: CustomerOut
    house: HouseOut
    members: list[ProjectMemberOut] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# ProjectMember
# -----------------------------------------------------------------------------
class ProjectMemberAdd(BaseModel):
    user_id: UUID
    role: ProjectRole = ProjectRole.MEMBER


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    user_id: UUID
    role: ProjectRole
    email: str
    full_name: str
    joined_at: datetime


ProjectDetail.model_rebuild()
