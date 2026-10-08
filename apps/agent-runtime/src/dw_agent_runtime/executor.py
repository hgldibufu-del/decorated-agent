"""ToolExecutor —— 需求文档 §12 的完整治理链。

    permission → schema → idempotency → concurrency → timeout → retry → fallback → audit

关键取舍：
* **只有可恢复错误才重试**：超时 / 下游不可用重试；权限、入参、幂等冲突重试没有意义，
  只会放大故障面；
* **降级只在最后一步**：原始工具穷尽重试仍失败才走 `fallback_tool_id`，
  且降级调用自身不会再触发降级（避免互相兜底死循环）；
* **审计不因失败而缺席**：拒绝、超时、降级都落 `tool_calls` + `audit_logs` 行；
* 禁止 `except Exception: pass` —— handler 崩溃会转成 `ToolUnavailableError` 并记录堆栈。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from dw_domain.errors import (
    ToolConflictError,
    ToolError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolUnavailableError,
    ToolValidationError,
)
from dw_domain.repositories.agent_runtime import AuditRepository, RunRepository
from dw_schemas.agent import ToolCallStatus
from dw_schemas.iam import UserIdentity
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.registry import ToolRegistry, ToolSpec, missing_scopes
from dw_agent_runtime.tools import BUILTIN_TOOLS, ToolContext, ToolDefinition
from dw_infrastructure.observability import record_error, record_ok, start_span

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_id: str
    output: dict
    attempt: int
    duration_ms: int
    replayed: bool = False
    fallback_used: bool = False


def is_retryable_tool_error(error: ToolError) -> bool:
    """只有「可恢复」的失败才值得重试。"""
    return isinstance(error, (ToolTimeoutError, ToolUnavailableError))


class ToolExecutor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        tools: ToolRegistry,
        actor: UserIdentity,
        run_id: UUID,
        task_id: UUID | None = None,
        definitions: Mapping[str, ToolDefinition] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        self._session = session
        self._tools = tools
        self._actor = actor
        self._run_id = run_id
        self._task_id = task_id
        self._definitions: Mapping[str, ToolDefinition] = (
            definitions if definitions is not None else BUILTIN_TOOLS
        )
        self._max_concurrency = max_concurrency
        self._runs = RunRepository(session)
        self._audit = AuditRepository(session)
        # 并发控制按工具维度限流：一个慢工具不应拖垮所有工具
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._key_guards: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ 入口
    async def call(
        self,
        tool_id: str,
        payload: dict,
        *,
        idempotency_key: str | None = None,
        _is_fallback: bool = False,
    ) -> ToolResult:
        """治理链入口；同时是一个 `tool.call` span —— **被拒绝的调用也会留下 span**。"""
        with start_span(
            "tool.call",
            attributes={
                "tool.id": tool_id,
                "tool.fallback": _is_fallback,
                "run.id": str(self._run_id),
            },
        ) as span:
            try:
                result = await self._call(
                    tool_id,
                    payload,
                    idempotency_key=idempotency_key,
                    _is_fallback=_is_fallback,
                )
            except ToolError as exc:
                span.set_attribute("tool.status", "error")
                record_error(span, exc)
                raise
            span.set_attribute("tool.status", "replayed" if result.replayed else "success")
            span.set_attribute("tool.attempt", result.attempt)
            span.set_attribute("tool.duration_ms", result.duration_ms)
            if result.fallback_used:
                span.set_attribute("tool.fallback_used", True)
            record_ok(span)
            return result

    async def _call(
        self,
        tool_id: str,
        payload: dict,
        *,
        idempotency_key: str | None = None,
        _is_fallback: bool = False,
    ) -> ToolResult:
        spec = self._tools.require(tool_id)

        definition = self._definitions.get(tool_id)
        if definition is None:
            raise ToolUnavailableError(f"工具已注册但没有实现: {tool_id}")

        missing = missing_scopes(self._actor, spec.required_scopes)
        if missing:
            await self._audit.record(
                action="tool_call_denied",
                resource_type="tool",
                resource_id=tool_id,
                actor_id=self._actor.user_id,
                run_id=self._run_id,
                details={"missing_scopes": missing},
            )
            raise ToolPermissionError(f"缺少工具 scope: {', '.join(missing)}")

        validated = self._validate(definition, payload)

        if spec.idempotency_required and not idempotency_key:
            raise ToolValidationError(f"工具 {tool_id} 要求提供 idempotency_key")

        guard: asyncio.Lock | None = None
        if idempotency_key:
            cached = await self._runs.find_successful_call(idempotency_key)
            if cached is not None:
                await self._audit.record(
                    action="tool_call_replayed",
                    resource_type="tool_call",
                    resource_id=str(cached.id),
                    actor_id=self._actor.user_id,
                    run_id=self._run_id,
                    details={"tool_id": tool_id, "idempotency_key": idempotency_key},
                )
                return ToolResult(
                    tool_id=tool_id,
                    output=dict(cached.output_payload),
                    attempt=cached.attempt,
                    duration_ms=cached.duration_ms,
                    replayed=True,
                )
            guard = self._key_guards.setdefault(idempotency_key, asyncio.Lock())
            if guard.locked():
                raise ToolConflictError(f"相同 idempotency_key 的调用正在进行: {idempotency_key}")
            await guard.acquire()

        try:
            return await self._execute(
                spec, definition, validated, payload, idempotency_key, _is_fallback
            )
        finally:
            if guard is not None and guard.locked():
                guard.release()

    # ------------------------------------------------------------------ 内部
    async def _execute(
        self,
        spec: ToolSpec,
        definition: ToolDefinition,
        validated: BaseModel,
        raw_payload: dict,
        idempotency_key: str | None,
        is_fallback: bool,
    ) -> ToolResult:
        semaphore = self._semaphores.setdefault(
            spec.tool_id, asyncio.Semaphore(self._max_concurrency)
        )
        started = perf_counter()
        last_error: ToolError = ToolUnavailableError("工具调用未产生结果")
        attempts = max(1, spec.retry_max_attempts)

        for attempt in range(1, attempts + 1):
            async with semaphore:
                try:
                    output = await asyncio.wait_for(
                        definition.handler(validated, self._tool_context()),
                        timeout=spec.timeout_ms / 1000,
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    last_error = ToolTimeoutError(
                        f"工具 {spec.tool_id} 调用超时（>{spec.timeout_ms}ms）"
                    )
                except ToolError as exc:
                    last_error = exc
                    if not is_retryable_tool_error(exc):
                        break
                except Exception as exc:  # 记录堆栈后归一化，绝不静默
                    logger.exception("tool handler crashed", extra={"tool_id": spec.tool_id})
                    last_error = ToolUnavailableError(f"工具 {spec.tool_id} 执行异常: {exc}")
                    break
                else:
                    duration_ms = int((perf_counter() - started) * 1000)
                    await self._record(
                        spec,
                        raw_payload,
                        output,
                        ToolCallStatus.SUCCESS,
                        attempt,
                        duration_ms,
                        None,
                        idempotency_key,
                    )
                    return ToolResult(spec.tool_id, output, attempt, duration_ms)

            if is_retryable_tool_error(last_error) and attempt < attempts:
                logger.warning(
                    "tool call retrying",
                    extra={"tool_id": spec.tool_id, "attempt": attempt},
                )
                await asyncio.sleep(spec.retry_backoff_ms / 1000)

        duration_ms = int((perf_counter() - started) * 1000)
        status = (
            ToolCallStatus.TIMEOUT
            if isinstance(last_error, ToolTimeoutError)
            else ToolCallStatus.FAILED
        )
        await self._record(
            spec, raw_payload, {}, status, attempts, duration_ms, str(last_error), idempotency_key
        )

        if not is_fallback and spec.fallback_tool_id:
            logger.warning(
                "tool call falling back",
                extra={"tool_id": spec.tool_id, "fallback": spec.fallback_tool_id},
            )
            fallback = await self.call(spec.fallback_tool_id, raw_payload, _is_fallback=True)
            return ToolResult(
                tool_id=spec.tool_id,
                output=fallback.output,
                attempt=attempts,
                duration_ms=duration_ms,
                fallback_used=True,
            )

        raise last_error

    def _validate(self, definition: ToolDefinition[Any], payload: dict) -> Any:
        try:
            return definition.input_model.model_validate(payload)
        except ValidationError as exc:
            problems = exc.errors()
            reason = problems[0]["msg"] if problems else str(exc)
            raise ToolValidationError(f"工具 {definition.tool_id} 入参校验失败: {reason}") from exc

    def _tool_context(self) -> ToolContext:
        return ToolContext(
            session=self._session,
            actor=self._actor,
            run_id=self._run_id,
            task_id=self._task_id,
        )

    async def _record(
        self,
        spec: ToolSpec,
        raw_payload: dict,
        output: dict,
        status: ToolCallStatus,
        attempt: int,
        duration_ms: int,
        error: str | None,
        idempotency_key: str | None,
    ) -> None:
        call = await self._runs.create_tool_call(
            run_id=self._run_id,
            task_id=self._task_id,
            tool_id=spec.tool_id,
            idempotency_key=idempotency_key,
            input_payload=raw_payload,
            output_payload=output,
            status=status.value,
            attempt=attempt,
            duration_ms=duration_ms,
            error=error,
        )
        if spec.audit_required:
            await self._audit.record(
                action="tool_call",
                resource_type="tool_call",
                resource_id=str(call.id),
                actor_id=self._actor.user_id,
                run_id=self._run_id,
                details={
                    "tool_id": spec.tool_id,
                    "status": status.value,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                },
            )
