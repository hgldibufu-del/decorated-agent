"""身份与授权表 —— 需求文档 §13 / §22。

表：users / roles / permissions / user_roles / role_permissions

设计说明：
* 角色与权限之间是**数据驱动的关联**（而不是代码里写死分支），这样 §13 的角色清单
  可以通过 seed 调整，不必改代码重新发布；
* `ondelete="CASCADE"` 用于纯关联表（删用户必须连带删掉他的角色关系，否则留下悬空行）；
* 口令散列格式写在 `dw_domain.security`，这里只是一个 255 长度的字符串列。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dw_domain.models.base import (
    Base,
    OptimisticLockMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )

    def permission_codes(self) -> list[str]:
        return sorted(permission.code for permission in self.permissions)


class Permission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, OptimisticLockMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    def role_names(self) -> list[str]:
        return sorted(role.name for role in self.roles)

    def permission_codes(self) -> list[str]:
        codes: set[str] = set()
        for role in self.roles:
            codes.update(role.permission_codes())
        return sorted(codes)
