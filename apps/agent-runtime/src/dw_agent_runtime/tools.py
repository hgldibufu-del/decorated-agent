"""内置工具定义 —— 需求文档 §11。

每个工具 = `Pydantic 入参模型 + handler`。
用 Pydantic 而不是 JSON Schema 字符串，好处是**校验即类型**：
入参非法时 Pydantic 抛错被转成 `ToolValidationError`，同时模型还能生成
注册中心要展示的 JSON Schema，两者不会不一致。

工具仍要过 Project ACL：工具能力 ≠ 数据权限，拿到 `project:read` 的人
若不是项目成员，依旧看不到项目。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from uuid import UUID

from dw_domain.access_control import AccessSubject, can_read_project
from dw_domain.errors import EntityNotFoundError, ToolPermissionError
from dw_domain.repositories.agent_runtime import RunRepository
from dw_domain.repositories.projects import ProjectRepository
from dw_schemas.agent import RiskLevel
from dw_schemas.iam import UserIdentity
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ToolContext:
    """handler 能拿到的最小上下文：不含任何 Agent 编排细节。"""

    session: AsyncSession
    actor: UserIdentity
    run_id: UUID | None
    task_id: UUID | None


InputModelT = TypeVar("InputModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[InputModelT]):
    """工具定义：入参模型与 handler 类型绑定，避免调用时靠约定保证正确性。"""

    tool_id: str
    description: str
    required_scopes: tuple[str, ...]
    risk_level: RiskLevel
    input_model: type[InputModelT]
    handler: Callable[[InputModelT, ToolContext], Awaitable[dict]]

    def input_schema(self) -> dict:
        return self.input_model.model_json_schema()


# -----------------------------------------------------------------------------
# project_query
# -----------------------------------------------------------------------------
class ProjectQueryIn(BaseModel):
    project_id: UUID


async def _project_query(payload: ProjectQueryIn, ctx: ToolContext) -> dict:
    projects = ProjectRepository(ctx.session)
    project, membership_role = await projects.find_access(payload.project_id, ctx.actor.user_id)
    if project is None:
        raise EntityNotFoundError(f"项目不存在: {payload.project_id}")

    subject = AccessSubject.from_iterable(
        is_admin=ctx.actor.is_admin,
        membership_role=membership_role,
        permissions=[permission.value for permission in ctx.actor.permissions],
    )
    if not can_read_project(subject):
        raise ToolPermissionError("无权访问该项目")

    return {
        "id": str(project.id),
        "code": project.code,
        "name": project.name,
        "status": project.status,
        "customer_name": project.customer.name,
        "house_address": project.house.address,
        "budget_amount": str(project.budget_amount) if project.budget_amount else None,
        "member_role": membership_role.value if membership_role else None,
    }


# -----------------------------------------------------------------------------
# project_list
# -----------------------------------------------------------------------------
class ProjectListIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


async def _project_list(payload: ProjectListIn, ctx: ToolContext) -> dict:
    projects = ProjectRepository(ctx.session)
    rows = await projects.list_for_user(
        ctx.actor.user_id, is_admin=ctx.actor.is_admin, limit=payload.limit
    )
    return {
        "projects": [
            {
                "id": str(project.id),
                "code": project.code,
                "name": project.name,
                "status": project.status,
                "customer_name": project.customer.name,
                "member_role": role.value if role else None,
            }
            for project, role in rows
        ]
    }


# -----------------------------------------------------------------------------
# artifact_query（§34：跨 Agent only 传 artifact_id）
# -----------------------------------------------------------------------------
class ArtifactQueryIn(BaseModel):
    artifact_id: UUID


async def _artifact_query(payload: ArtifactQueryIn, ctx: ToolContext) -> dict:
    runs = RunRepository(ctx.session)
    artifact = await runs.get_artifact(payload.artifact_id)
    if artifact is None:
        raise EntityNotFoundError(f"Artifact 不存在: {payload.artifact_id}")

    run = await runs.get_run(artifact.run_id)
    is_owner = run is not None and str(run.requester_id) == str(ctx.actor.user_id)
    if not (ctx.actor.is_admin or is_owner):
        raise ToolPermissionError("只能查询自己发起的 Run 产出的 Artifact")

    return {
        "artifact_id": str(artifact.id),
        "run_id": str(artifact.run_id),
        "artifact_type": artifact.artifact_type,
        "producer": artifact.producer,
        "version": artifact.version,
        "payload": artifact.payload,
    }


BUILTIN_TOOLS: dict[str, ToolDefinition[Any]] = {
    "project_query": ToolDefinition(
        tool_id="project_query",
        description="按 ID 查询单个项目（受 Project ACL 约束）",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=ProjectQueryIn,
        handler=_project_query,
    ),
    "project_list": ToolDefinition(
        tool_id="project_list",
        description="列出当前用户可见的项目",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=ProjectListIn,
        handler=_project_list,
    ),
    "artifact_query": ToolDefinition(
        tool_id="artifact_query",
        description="按 ID 读取 Artifact 内容",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=ArtifactQueryIn,
        handler=_artifact_query,
    ),
}

# Phase 4：AfterSales 工具（RAG 驱动），见 rag_tools.py
from dw_agent_runtime.rag_tools import AFTERSALES_TOOLS  # noqa: E402

BUILTIN_TOOLS.update(AFTERSALES_TOOLS)

# Phase 5：Quote 工具（业务表驱动），见 quote_tools.py
from dw_agent_runtime.quote_tools import QUOTE_TOOLS  # noqa: E402

BUILTIN_TOOLS.update(QUOTE_TOOLS)

# Phase 6：Design 工具（业务表驱动），见 design_tools.py
from dw_agent_runtime.design_tools import DESIGN_TOOLS  # noqa: E402

BUILTIN_TOOLS.update(DESIGN_TOOLS)

# Phase 7：Construction 工具（业务表驱动），见 construction_tools.py
from dw_agent_runtime.construction_tools import CONSTRUCTION_TOOLS  # noqa: E402

BUILTIN_TOOLS.update(CONSTRUCTION_TOOLS)

# Phase 10：记忆工具（受治理），见 memory_tools.py
from dw_agent_runtime.memory_tools import MEMORY_TOOLS  # noqa: E402

BUILTIN_TOOLS.update(MEMORY_TOOLS)
