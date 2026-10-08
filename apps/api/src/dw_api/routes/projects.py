"""项目路由 —— 需求文档 §21 的 Project 接口 + §13 的 Project ACL。

Controller 只做三件事：取身份 → 调应用服务 → 返回契约。
业务规则（谁可见、谁能改）全部在 `dw_domain`，这里一条 SQL 都没有。
"""

from __future__ import annotations

from uuid import UUID

from dw_domain.services import ProjectService
from dw_schemas.iam import PermissionCode, UserIdentity
from dw_schemas.project import (
    ProjectCreate,
    ProjectDetail,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectSummary,
    ProjectUpdate,
)
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import current_identity, get_db_session, require_permissions

router = APIRouter(tags=["projects"])


@router.get(
    "/projects",
    response_model=list[ProjectSummary],
    summary="列出当前可见的项目（按 Project ACL 收敛）",
)
async def list_projects(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectSummary]:
    service = ProjectService(session)
    return await service.list_projects(identity)


@router.post(
    "/projects",
    response_model=ProjectDetail,
    status_code=201,
    summary="新建项目（创建者自动成为 owner）",
    responses={
        400: {"description": "客户/房屋不存在或房屋不属于该客户"},
        409: {"description": "项目编号已存在"},
    },
)
async def create_project(
    payload: ProjectCreate,
    identity: UserIdentity = Depends(require_permissions(PermissionCode.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectDetail:
    service = ProjectService(session)
    return await service.create_project(payload, identity)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    summary="查询项目详情",
    responses={403: {"description": "不是项目成员，无权访问"}, 404: {"description": "项目不存在"}},
)
async def get_project(
    project_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectDetail:
    service = ProjectService(session)
    return await service.get_project(project_id, identity)


@router.get(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberOut],
    summary="列出项目成员",
)
async def list_project_members(
    project_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectMemberOut]:
    service = ProjectService(session)
    return await service.list_members(project_id, identity)


@router.post(
    "/projects/{project_id}/members",
    response_model=list[ProjectMemberOut],
    summary="新增或更新项目成员",
    responses={403: {"description": "无权管理该项目成员"}},
)
async def add_project_member(
    project_id: UUID,
    payload: ProjectMemberAdd,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectMemberOut]:
    service = ProjectService(session)
    return await service.add_member(project_id, payload, identity)


@router.put(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    summary="编辑项目（乐观锁）",
    responses={
        403: {"description": "不是项目 owner/manager，或缺少 project:write"},
        409: {"description": "版本冲突（并发编辑）：请重新读取后再改"},
    },
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectDetail:
    service = ProjectService(session)
    return await service.update_project(project_id, payload, identity)


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    response_class=Response,
    summary="删除项目",
    responses={409: {"description": "仍被 Run / 施工记录引用，无法删除"}},
)
async def delete_project(
    project_id: UUID,
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    service = ProjectService(session)
    await service.delete_project(project_id, identity)
    return Response(status_code=204)
