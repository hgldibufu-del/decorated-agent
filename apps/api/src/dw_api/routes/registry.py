"""注册中心只读接口 —— 需求文档 §6 / §21。

只读：注册中心的写入走 seed / 迁移，不允许通过 HTTP 随意注册 Agent，
否则「Supervisor 只能从 Registry 选合法 Agent」这条约束会被轻易绕过。
"""

from __future__ import annotations

from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_schemas.agent import AgentOut, SkillOut, ToolOut
from dw_schemas.iam import UserIdentity
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dw_api.auth import current_identity, get_db_session

router = APIRouter(tags=["registry"])


@router.get("/agents", response_model=list[AgentOut], summary="Agent 注册中心")
async def list_agents(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentOut]:
    models = await RegistryRepository(session).list_agents()
    return [
        AgentOut(
            agent_id=model.agent_id,
            agent_type=model.agent_type_enum,
            description=model.description,
            version=model.version,
            supported_skills=list(model.supported_skills or []),
            required_scopes=list(model.required_scopes or []),
            enabled=model.enabled,
        )
        for model in models
    ]


@router.get("/skills", response_model=list[SkillOut], summary="Skill 注册中心")
async def list_skills(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[SkillOut]:
    models = await RegistryRepository(session).list_skills()
    return [
        SkillOut(
            skill_id=model.skill_id,
            agent_type=model.agent_type_enum,
            version=model.version,
            required_scopes=list(model.required_scopes or []),
            risk_level=model.risk_enum,
            allowed_tools=list(model.allowed_tools or []),
            enabled=model.enabled,
        )
        for model in models
    ]


@router.get("/tools", response_model=list[ToolOut], summary="Tool 注册中心")
async def list_tools(
    identity: UserIdentity = Depends(current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[ToolOut]:
    models = await RegistryRepository(session).list_tools()
    return [
        ToolOut(
            tool_id=model.tool_id,
            description=model.description,
            required_scopes=list(model.required_scopes or []),
            risk_level=model.risk_enum,
            timeout_ms=model.timeout_ms,
            retry_max_attempts=model.retry_max_attempts,
            fallback_tool_id=model.fallback_tool_id,
            idempotency_required=model.idempotency_required,
            audit_required=model.audit_required,
            enabled=model.enabled,
        )
        for model in models
    ]
