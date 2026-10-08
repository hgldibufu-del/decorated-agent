"""角色 → 权限的默认矩阵 —— 需求文档 §13。

放在领域层而不是 seed 脚本里，是为了让 **seed、集成测试、未来 Phase 的权限文档**
共用同一份定义：否则很容易出现「本地演示的权限」与「测试假设的权限」悄悄分叉。
"""

from __future__ import annotations

from dw_schemas.iam import PermissionCode, RoleName

ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleName.ADMIN.value: [permission.value for permission in PermissionCode],
    RoleName.PROJECT_MANAGER.value: [
        PermissionCode.PROJECT_READ.value,
        PermissionCode.PROJECT_WRITE.value,
        PermissionCode.QUOTE_READ.value,
        PermissionCode.QUOTE_WRITE.value,
        PermissionCode.MATERIAL_READ.value,
        PermissionCode.CONSTRUCTION_READ.value,
        PermissionCode.AFTERSALES_READ.value,
        PermissionCode.DESIGN_READ.value,
        PermissionCode.MEMORY_READ.value,
        PermissionCode.MEMORY_WRITE.value,
    ],
    RoleName.DESIGNER.value: [
        PermissionCode.PROJECT_READ.value,
        PermissionCode.QUOTE_READ.value,
        PermissionCode.MATERIAL_READ.value,
        PermissionCode.DESIGN_READ.value,
        PermissionCode.MEMORY_READ.value,
        PermissionCode.MEMORY_WRITE.value,
    ],
    RoleName.ESTIMATOR.value: [
        PermissionCode.PROJECT_READ.value,
        PermissionCode.QUOTE_READ.value,
        PermissionCode.QUOTE_WRITE.value,
        PermissionCode.MATERIAL_READ.value,
        PermissionCode.MEMORY_READ.value,
        PermissionCode.MEMORY_WRITE.value,
    ],
    RoleName.CONSTRUCTION_MANAGER.value: [
        PermissionCode.PROJECT_READ.value,
        PermissionCode.CONSTRUCTION_READ.value,
        PermissionCode.MEMORY_READ.value,
        PermissionCode.MEMORY_WRITE.value,
    ],
    RoleName.AFTERSALES.value: [
        PermissionCode.PROJECT_READ.value,
        PermissionCode.AFTERSALES_READ.value,
        PermissionCode.AFTERSALES_WRITE.value,
        PermissionCode.MEMORY_READ.value,
        PermissionCode.MEMORY_WRITE.value,
    ],
    RoleName.VIEWER.value: [
        PermissionCode.PROJECT_READ.value,
    ],
}


def permissions_for(role: RoleName) -> list[str]:
    return list(ROLE_PERMISSIONS[role.value])
