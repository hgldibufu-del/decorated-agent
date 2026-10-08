"""注册中心 ↔ MCP 工具 桥接。

* `list_tools`：从**数据库注册中心**取「已启用」工具，联合 `ToolDefinition` 生成 MCP 工具描述
  （含由 Pydantic 入参模型导出的 `inputSchema`）；
* `call_tool`：经 `ToolExecutor` 执行 —— scope / schema / 幂等 / 超时 / 重试 / 审计**一步不落**，
  与 HTTP 入口的治理口径完全一致。

审计归属：MCP 没有 Run 概念，这里为每个身份**懒创建一个「MCP 会话 Run」**，
让 `tool_calls` / `audit_logs` 有归属，而不是产生无主记录。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.registry import RuntimeRegistries, ToolSpec
from dw_agent_runtime.tools import BUILTIN_TOOLS, ToolDefinition
from dw_domain.errors import TokenError
from dw_domain.repositories.agent_runtime import RunRepository
from dw_domain.security import decode_access_token
from dw_infrastructure.db import Database
from dw_schemas.agent import RunMode, RunStatus
from dw_schemas.iam import UserIdentity

from dw_mcp_server.protocol import McpAuthError, extract_bearer

SESSION_RUN_OBJECTIVE = "MCP 会话"


def tool_descriptor(spec: ToolSpec, definition: ToolDefinition | None) -> dict[str, Any]:
    """把注册中心条目 + 工具定义合成 MCP 工具描述。"""
    schema = (
        definition.input_schema()
        if definition is not None
        else {"type": "object", "properties": {}}
    )
    return {"name": spec.tool_id, "description": spec.description, "inputSchema": schema}


class McpBridge:
    def __init__(
        self,
        database: Database,
        *,
        secret_key: str,
        service_token: str | None = None,
    ) -> None:
        self._database = database
        self._secret_key = secret_key
        self._service_token = service_token
        self._session_runs: dict[str, UUID] = {}

    async def dispose(self) -> None:
        """释放底层数据库连接（供进程退出或测试收尾调用）。"""
        await self._database.dispose()

    async def list_tools(self) -> list[dict[str, Any]]:
        async with self._database.session() as session:
            registries = await RuntimeRegistries.load(session)
            descriptors = [
                tool_descriptor(spec, BUILTIN_TOOLS.get(spec.tool_id))
                for spec in registries.tools.all()
            ]
        descriptors.sort(key=lambda item: item["name"])
        return descriptors

    def resolve_actor(self, meta: dict[str, Any] | None) -> UserIdentity:
        """从 `_meta.authorization` 或 `DW_MCP_TOKEN` 解析调用身份（不查库）。"""
        token: str | None = None
        if isinstance(meta, dict):
            token = extract_bearer(meta.get("authorization"))
        token = token or self._service_token
        if not token:
            raise McpAuthError(
                "缺少鉴权令牌：请在 params._meta.authorization 提供 Bearer 令牌，或配置 DW_MCP_TOKEN"
            )
        try:
            return decode_access_token(token, secret_key=self._secret_key)
        except TokenError as exc:
            raise McpAuthError(f"令牌无效: {exc}") from exc

    async def call_tool(
        self, name: str, arguments: dict[str, Any], actor: UserIdentity
    ) -> dict[str, Any]:
        run_id = await self._session_run(actor)
        async with self._database.session() as session:
            registries = await RuntimeRegistries.load(session)
            executor = ToolExecutor(
                session=session,
                tools=registries.tools,
                actor=actor,
                run_id=run_id,
                definitions=BUILTIN_TOOLS,
            )
            result = await executor.call(name, dict(arguments))
            return result.output

    async def _session_run(self, actor: UserIdentity) -> UUID:
        key = str(actor.user_id)
        cached = self._session_runs.get(key)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            run = await RunRepository(session).create_run(
                objective=SESSION_RUN_OBJECTIVE,
                requester_id=actor.user_id,
                mode=RunMode.DIRECT,
                status=RunStatus.RUNNING,
            )
            run_id = run.id
        self._session_runs[key] = run_id
        return run_id
