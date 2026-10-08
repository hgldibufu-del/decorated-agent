"""RBAC + Project ACL 判定规则单测。

这里是全系统最容易出安全事故的地方，所以矩阵被拆得很细，
每个格子都有独立用例，而不是只测 happy path。
"""

from __future__ import annotations

import pytest
from dw_domain.access_control import (
    AccessSubject,
    can_manage_members,
    can_read_project,
    can_use_tool_scope,
    can_write_project,
    is_project_member,
)
from dw_schemas.iam import PermissionCode, ProjectRole


def subject(is_admin: bool, role: ProjectRole | None, permissions: list[str]) -> AccessSubject:
    return AccessSubject(
        is_admin=is_admin,
        membership_role=role,
        granted_permissions=frozenset(permissions),
    )


ALL_PERMISSIONS = [permission.value for permission in PermissionCode]
READ_ONLY = [PermissionCode.PROJECT_READ.value]


def test_admin_sees_everything_without_membership():
    admin = subject(True, None, [])
    assert is_project_member(admin) is True
    assert can_read_project(admin) is True
    assert can_write_project(admin) is True
    assert can_manage_members(admin) is True


def test_non_member_is_denied_even_with_permissions():
    """持有 tool scope 但不是项目成员 → 必须拒绝。

    否则任何预算员都能看到全公司的项目，Project ACL 就形同虚设。
    """
    intruder = subject(False, None, ALL_PERMISSIONS)
    assert is_project_member(intruder) is False
    assert can_read_project(intruder) is False
    assert can_write_project(intruder) is False


@pytest.mark.parametrize(
    "role",
    [ProjectRole.OWNER, ProjectRole.MANAGER, ProjectRole.MEMBER, ProjectRole.VIEWER],
)
def test_every_membership_role_can_read(role: ProjectRole):
    member = subject(False, role, READ_ONLY)
    assert can_read_project(member) is True


def test_member_without_read_scope_cannot_read():
    member = subject(False, ProjectRole.MEMBER, [])
    assert can_read_project(member) is False


@pytest.mark.parametrize("role", [ProjectRole.OWNER, ProjectRole.MANAGER])
def test_owner_and_manager_can_write(role: ProjectRole):
    member = subject(
        False,
        role,
        [PermissionCode.PROJECT_READ.value, PermissionCode.PROJECT_WRITE.value],
    )
    assert can_write_project(member) is True
    assert can_manage_members(member) is True


@pytest.mark.parametrize("role", [ProjectRole.MEMBER, ProjectRole.VIEWER])
def test_ordinary_member_cannot_write(role: ProjectRole):
    member = subject(
        False,
        role,
        [PermissionCode.PROJECT_READ.value, PermissionCode.PROJECT_WRITE.value],
    )
    assert can_write_project(member) is False


def test_write_role_without_write_scope_is_denied():
    """成员是 owner，但没有 project:write → 仍然不能改。"""
    member = subject(False, ProjectRole.OWNER, READ_ONLY)
    assert can_write_project(member) is False


def test_tool_scope_check_is_independent_of_membership():
    estimator = subject(
        False,
        None,
        [PermissionCode.PROJECT_READ.value, PermissionCode.QUOTE_WRITE.value],
    )
    assert can_use_tool_scope(estimator, PermissionCode.QUOTE_WRITE) is True
    assert can_use_tool_scope(estimator, PermissionCode.AFTERSALES_WRITE) is False


def test_subject_factory_accepts_iterable():
    built = AccessSubject.from_iterable(
        is_admin=False,
        membership_role=ProjectRole.VIEWER,
        permissions=(PermissionCode.PROJECT_READ.value,),
    )
    assert built.granted_permissions == frozenset({PermissionCode.PROJECT_READ.value})
