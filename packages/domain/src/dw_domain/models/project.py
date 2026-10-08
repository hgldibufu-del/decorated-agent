"""项目域主表 —— 需求文档 §9 / §22。

表：customers / houses / projects / project_members

外键删除策略刻意区分：
* Customer / House 被 Project 引用 → `RESTRICT`：业务事实不允许被连坐删除，
  误删客户会把历史项目的档案一起抹掉；
* Project → ProjectMember → `CASCADE`：成员关系依附于项目，项目删除时一并清理。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from dw_schemas.iam import ProjectRole
from dw_schemas.project import ProjectStatus
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dw_domain.models.base import (
    Base,
    OptimisticLockMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utc_now,
)
from dw_domain.models.iam import User


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(2000))

    houses: Mapped[list[House]] = relationship(back_populates="customer", lazy="selectin")


class House(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "houses"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(64))
    area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    layout: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(2000))

    customer: Mapped[Customer] = relationship(lazy="selectin")


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin, OptimisticLockMixin):
    __tablename__ = "projects"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.DRAFT.value
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="RESTRICT"), nullable=False
    )
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_complete_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(2000))

    customer: Mapped[Customer] = relationship(lazy="selectin")
    house: Mapped[House] = relationship(lazy="selectin")
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def status_enum(self) -> ProjectStatus:
        return ProjectStatus(self.status)


class ProjectMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (
        # 同一项目内同一用户只允许一条成员关系，避免权限叠加歧义
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_id_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ProjectRole.MEMBER.value)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(lazy="selectin")

    @property
    def role_enum(self) -> ProjectRole:
        return ProjectRole(self.role)
