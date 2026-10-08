"""ToolExecutor 治理链端到端（真实 PostgreSQL，事务回滚不落库）。

每个环节一个用例：权限 / 入参 / 幂等 / 并发 / 超时 / 重试 / 降级 / 审计。
这里用注入的假工具（假的 handler + 内存中构造的 ToolSpec），
目的是把治理链本身与业务工具实现解耦，避免用例互相牵连。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

import pytest
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.registry import ToolRegistry, ToolSpec
from dw_agent_runtime.tools import ToolDefinition
from dw_domain.errors import (
    ToolConflictError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolUnavailableError,
    ToolValidationError,
)
from dw_domain.models.agent_runtime import AuditLog, ToolCall
from dw_domain.repositories.agent_runtime import RunRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import RiskLevel
from dw_schemas.iam import PermissionCode, RoleName, UserIdentity
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


class Empty(BaseModel):
    model_config = {"extra": "forbid"}


class NeedNumber(BaseModel):
    number: int


async def ok_handler(payload: BaseModel, ctx) -> dict:
    return {"value": 1}


def tool_def(
    tool_id: str, handler: Callable, input_model: type[BaseModel] = Empty
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        description=tool_id,
        required_scopes=(),
        risk_level=RiskLevel.L0,
        input_model=input_model,
        handler=handler,
    )


def spec(
    tool_id: str,
    *,
    scopes: tuple[str, ...] = (),
    timeout_ms: int = 5000,
    attempts: int = 1,
    backoff_ms: int = 1,
    fallback: str | None = None,
    idempotency: bool = False,
    audit: bool = True,
) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description=tool_id,
        required_scopes=scopes,
        risk_level=RiskLevel.L0,
        timeout_ms=timeout_ms,
        retry_max_attempts=attempts,
        retry_backoff_ms=backoff_ms,
        fallback_tool_id=fallback,
        idempotency_required=idempotency,
        audit_required=audit,
        enabled=True,
    )


@pytest.fixture
async def env_factory(make_user):
    database = Database.from_settings(get_settings())
    opened: list[AsyncSession] = []

    async def factory(
        *,
        tools: list[ToolSpec],
        definitions: dict[str, ToolDefinition],
        permissions: list[PermissionCode] | None = None,
        admin: bool = False,
    ):
        user = await make_user(role=RoleName.ADMIN if admin else RoleName.PROJECT_MANAGER)
        session = database.session_factory()
        opened.append(session)
        run = await RunRepository(session).create_run(
            objective="治理链测试", requester_id=UUID(user["id"])
        )
        await session.flush()
        identity = UserIdentity(
            user_id=UUID(user["id"]),
            email=user["email"],
            full_name="治理链测试",
            roles=[RoleName.ADMIN] if admin else [RoleName.PROJECT_MANAGER],
            permissions=permissions if permissions is not None else [PermissionCode.PROJECT_READ],
        )
        executor = ToolExecutor(
            session=session,
            tools=ToolRegistry(tools),
            actor=identity,
            run_id=run.id,
            definitions=definitions,
        )
        return executor, run.id, session

    yield factory

    for session in opened:
        await session.rollback()
        await session.close()
    await database.dispose()


async def count_calls(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(select(ToolCall.id).where(ToolCall.run_id == run_id))
    return len(result.scalars().all())


async def audit_actions(session: AsyncSession, run_id: UUID) -> list[str]:
    result = await session.execute(select(AuditLog.action).where(AuditLog.run_id == run_id))
    return list(result.scalars().all())


# -----------------------------------------------------------------------------
# 权限
# -----------------------------------------------------------------------------
async def test_missing_scope_is_denied_and_audited(env_factory):
    executor, run_id, session = await env_factory(
        tools=[spec("secret_tool", scopes=("aftersales:write",))],
        definitions={"secret_tool": tool_def("secret_tool", ok_handler)},
    )

    with pytest.raises(ToolPermissionError):
        await executor.call("secret_tool", {})

    assert await count_calls(session, run_id) == 0
    assert "tool_call_denied" in await audit_actions(session, run_id)


async def test_admin_bypasses_scope_check(env_factory):
    executor, _, _ = await env_factory(
        tools=[spec("secret_tool", scopes=("aftersales:write",))],
        definitions={"secret_tool": tool_def("secret_tool", ok_handler)},
        admin=True,
    )
    result = await executor.call("secret_tool", {})
    assert result.output == {"value": 1}


# -----------------------------------------------------------------------------
# 入参校验
# -----------------------------------------------------------------------------
async def test_invalid_payload_raises_validation_error(env_factory):
    executor, run_id, session = await env_factory(
        tools=[spec("typed_tool")],
        definitions={"typed_tool": tool_def("typed_tool", ok_handler, NeedNumber)},
    )

    with pytest.raises(ToolValidationError):
        await executor.call("typed_tool", {"number": "not-a-number"})

    assert await count_calls(session, run_id) == 0


# -----------------------------------------------------------------------------
# 超时
# -----------------------------------------------------------------------------
async def test_timeout_raises_tool_timeout_and_records_call(env_factory):
    async def slow(payload: BaseModel, ctx) -> dict:
        await asyncio.sleep(1.0)
        return {}

    executor, run_id, session = await env_factory(
        tools=[spec("slow_tool", timeout_ms=100, attempts=1)],
        definitions={"slow_tool": tool_def("slow_tool", slow)},
    )

    with pytest.raises(ToolTimeoutError):
        await executor.call("slow_tool", {})

    assert await count_calls(session, run_id) == 1
    result = await session.execute(
        text("SELECT status FROM tool_calls WHERE run_id = :rid"), {"rid": str(run_id)}
    )
    assert result.scalar_one() == "timeout"


# -----------------------------------------------------------------------------
# 重试
# -----------------------------------------------------------------------------
async def test_retries_recoverable_error_then_succeeds(env_factory):
    state = {"calls": 0}

    async def flaky(payload: BaseModel, ctx) -> dict:
        state["calls"] += 1
        if state["calls"] == 1:
            raise ToolUnavailableError("下游抖动")
        return {"value": state["calls"]}

    executor, _, _ = await env_factory(
        tools=[spec("flaky_tool", attempts=3, backoff_ms=1)],
        definitions={"flaky_tool": tool_def("flaky_tool", flaky)},
    )

    result = await executor.call("flaky_tool", {})
    assert result.attempt == 2
    assert result.output == {"value": 2}


async def test_validation_error_is_not_retried(env_factory):
    state = {"calls": 0}

    async def broken(payload: BaseModel, ctx) -> dict:
        state["calls"] += 1
        raise ToolValidationError("参数永远不对")

    executor, _, _ = await env_factory(
        tools=[spec("broken_tool", attempts=3, backoff_ms=1)],
        definitions={"broken_tool": tool_def("broken_tool", broken)},
    )

    with pytest.raises(ToolValidationError):
        await executor.call("broken_tool", {})

    assert state["calls"] == 1, "不可恢复的错误重试没有意义"


async def test_handler_crash_becomes_unavailable_error(env_factory):
    async def crash(payload: BaseModel, ctx) -> dict:
        raise ValueError("boom")

    executor, _, _ = await env_factory(
        tools=[spec("crash_tool", attempts=1)],
        definitions={"crash_tool": tool_def("crash_tool", crash)},
    )

    with pytest.raises(ToolUnavailableError):
        await executor.call("crash_tool", {})


# -----------------------------------------------------------------------------
# 降级
# -----------------------------------------------------------------------------
async def test_fallback_is_used_after_exhausted_retries(env_factory):
    async def broken(payload: BaseModel, ctx) -> dict:
        raise ToolUnavailableError("主工具不可用")

    executor, _, _ = await env_factory(
        tools=[spec("primary", attempts=1, fallback="backup"), spec("backup")],
        definitions={
            "primary": tool_def("primary", broken),
            "backup": tool_def("backup", ok_handler),
        },
    )

    result = await executor.call("primary", {})
    assert result.fallback_used is True
    assert result.output == {"value": 1}


async def test_fallback_does_not_loop(env_factory):
    """两个工具互相兜底时不能无限递归。"""

    async def broken(payload: BaseModel, ctx) -> dict:
        raise ToolUnavailableError("down")

    executor, _, _ = await env_factory(
        tools=[
            spec("a", attempts=1, fallback="b"),
            spec("b", attempts=1, fallback="a"),
        ],
        definitions={"a": tool_def("a", broken), "b": tool_def("b", broken)},
    )

    with pytest.raises(ToolUnavailableError):
        await executor.call("a", {})


# -----------------------------------------------------------------------------
# 幂等
# -----------------------------------------------------------------------------
async def test_same_idempotency_key_replays_previous_result(env_factory):
    executor, run_id, session = await env_factory(
        tools=[spec("idem_tool")],
        definitions={"idem_tool": tool_def("idem_tool", ok_handler)},
    )

    first = await executor.call("idem_tool", {}, idempotency_key="key-1")
    second = await executor.call("idem_tool", {}, idempotency_key="key-1")

    assert first.replayed is False
    assert second.replayed is True
    assert second.output == first.output
    # 只落一条调用记录：重复请求没有真的重复执行
    assert await count_calls(session, run_id) == 1
    assert "tool_call_replayed" in await audit_actions(session, run_id)


async def test_idempotency_required_without_key_is_rejected(env_factory):
    executor, _, _ = await env_factory(
        tools=[spec("idem_tool", idempotency=True)],
        definitions={"idem_tool": tool_def("idem_tool", ok_handler)},
    )

    with pytest.raises(ToolValidationError):
        await executor.call("idem_tool", {})


async def test_concurrent_same_key_raises_conflict(env_factory):
    async def slow(payload: BaseModel, ctx) -> dict:
        await asyncio.sleep(0.6)
        return {"value": 1}

    executor, _, _ = await env_factory(
        tools=[spec("slow_tool")],
        definitions={"slow_tool": tool_def("slow_tool", slow)},
    )

    first = asyncio.create_task(executor.call("slow_tool", {}, idempotency_key="k"))
    await asyncio.sleep(0.15)
    second = asyncio.create_task(executor.call("slow_tool", {}, idempotency_key="k"))

    outcomes = await asyncio.gather(first, second, return_exceptions=True)

    assert not isinstance(outcomes[0], BaseException)
    assert isinstance(outcomes[1], ToolConflictError)


# -----------------------------------------------------------------------------
# 审计
# -----------------------------------------------------------------------------
async def test_successful_call_is_audited(env_factory):
    executor, run_id, session = await env_factory(
        tools=[spec("ok_tool")],
        definitions={"ok_tool": tool_def("ok_tool", ok_handler)},
    )

    await executor.call("ok_tool", {})

    assert await count_calls(session, run_id) == 1
    assert "tool_call" in await audit_actions(session, run_id)


async def test_audit_can_be_turned_off_per_tool(env_factory):
    executor, run_id, session = await env_factory(
        tools=[spec("quiet_tool", audit=False)],
        definitions={"quiet_tool": tool_def("quiet_tool", ok_handler)},
    )

    await executor.call("quiet_tool", {})

    # 调用记录仍要留（用于排查），但不写审计流水
    assert await count_calls(session, run_id) == 1
    assert await audit_actions(session, run_id) == []
