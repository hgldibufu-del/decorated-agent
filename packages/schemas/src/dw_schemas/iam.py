"""IAM 契约 —— 需求文档 §13（JWT / RBAC / Project ACL）。

只描述「身份与授权的形状」，不含任何 IO 与密码学实现（后者在 `dw_domain.security`）。

刻意选择：
* 邮箱用正则约束而非 `EmailStr`，避免仅为校验再引入 email-validator 依赖；
* 角色与权限是**枚举**，保证 Python / 数据库 / 前端三处能对得上；新增权限必须改这里，
  不允许在别处硬编码字符串（否则 Tool Scope 治理无从谈起）。
"""

from __future__ import annotations

import re
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RoleName(str, Enum):
    """全局角色（RBAC）。与 §13 要求的角色清单一致。"""

    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    DESIGNER = "designer"
    ESTIMATOR = "estimator"
    CONSTRUCTION_MANAGER = "construction_manager"
    AFTERSALES = "aftersales"
    VIEWER = "viewer"


class PermissionCode(str, Enum):
    """工具 / 资源 Scope。后续 Tool Registry 的 required_scopes 直接复用此枚举。"""

    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    QUOTE_READ = "quote:read"
    QUOTE_WRITE = "quote:write"
    MATERIAL_READ = "material:read"
    CONSTRUCTION_READ = "construction:read"
    AFTERSALES_READ = "aftersales:read"
    AFTERSALES_WRITE = "aftersales:write"
    DESIGN_READ = "design:read"
    # Phase 10：长期记忆。read 控制「是否加载画像」，write 控制「是否允许写入记忆」
    # （自动抽取同样受 write 约束 —— 记忆写入门禁只有一处，不搞例外）
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"


class ProjectRole(str, Enum):
    """项目内成员角色（Project ACL 的粒度）。"""

    OWNER = "owner"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"


def all_permission_codes() -> list[str]:
    return [permission.value for permission in PermissionCode]


# -----------------------------------------------------------------------------
# 认证
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(..., min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="有效期（秒）")


class UserIdentity(BaseModel):
    """登录成功后放入令牌的精简身份。"""

    user_id: UUID
    email: str
    full_name: str
    roles: list[RoleName] = Field(default_factory=list)
    permissions: list[PermissionCode] = Field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return RoleName.ADMIN in self.roles


class UserBrief(BaseModel):
    """成员候选所需的最小用户信息（不含角色/权限，避免泄露越权线索）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str


class UserSummary(BaseModel):
    """对外暴露的用户信息（不含凭据）。

    from_attributes=True：允许直接由 ORM 对象构造，避免在 Controller 里手写字段搬运。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    is_active: bool
    roles: list[RoleName] = Field(default_factory=list)
    permissions: list[PermissionCode] = Field(default_factory=list)
