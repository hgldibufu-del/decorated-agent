"""RBAC + Project ACL 判定规则 —— 需求文档 §13。

**这里全是纯函数，不碰数据库**。原因是授权逻辑是系统里最需要被反复审查的部分，
把它独立出来可以在毫秒级完成单测覆盖，不必起容器。

规则口径（唯一权威定义）：

1. `admin` 角色对所有项目拥有读 / 写权限；
2. 其他角色必须**先是项目成员**才谈得上权限 —— 「有 tool scope 但不是项目成员」应被拒绝，
   否则任何预算员都能看到全公司项目；
3. 项目读权限要求 way 成员且持有 `project:read`；
4. 项目写权限要求成员角色为 `owner` / `manager` 且持有 `project:write`。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from dw_schemas.iam import PermissionCode, ProjectRole

PROJECT_WRITE_ROLES = frozenset({ProjectRole.OWNER, ProjectRole.MANAGER})


@dataclass(frozen=True, slots=True)
class AccessSubject:
    """一次判定所需的全部输入：缺一项都无法得出「允许」。"""

    is_admin: bool
    membership_role: ProjectRole | None
    granted_permissions: frozenset[str]

    @classmethod
    def from_iterable(
        cls, *, is_admin: bool, membership_role: ProjectRole | None, permissions: Iterable[str]
    ) -> AccessSubject:
        return cls(
            is_admin=is_admin,
            membership_role=membership_role,
            granted_permissions=frozenset(permissions),
        )

    def has(self, code: PermissionCode) -> bool:
        """是否持有某个 tool scope（不涉及项目归属）。"""
        return code.value in self.granted_permissions


def is_project_member(subject: AccessSubject) -> bool:
    return subject.is_admin or subject.membership_role is not None


def can_read_project(subject: AccessSubject) -> bool:
    if subject.is_admin:
        return True
    if subject.membership_role is None:
        return False
    return subject.has(PermissionCode.PROJECT_READ)


def can_write_project(subject: AccessSubject) -> bool:
    if subject.is_admin:
        return True
    if subject.membership_role is None:
        return False
    if subject.membership_role not in PROJECT_WRITE_ROLES:
        return False
    return subject.has(PermissionCode.PROJECT_WRITE)


def can_manage_members(subject: AccessSubject) -> bool:
    """成员管理复用写权限：不额外引入新的 scope，避免 §13 的权限清单被撑大。"""
    return can_write_project(subject)


def can_use_tool_scope(subject: AccessSubject, code: PermissionCode) -> bool:
    """工具调用前的 scope 检查（Phase 2 起由 ToolExecutor 复用）。"""
    return subject.is_admin or subject.has(code)
