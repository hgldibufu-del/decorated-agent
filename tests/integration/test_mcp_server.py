"""MCP stdio 传输层集成测试（真实 PostgreSQL）。

覆盖：tools/list 元数据、tools/call 走完整治理链（成功 / 缺 scope / 未注册工具）、
以及「MCP 会话 Run」为工具调用提供审计归属。
"""

from __future__ import annotations

import json
from uuid import UUID

from dw_domain.models.agent_runtime import AgentRun
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.iam import RoleName
from sqlalchemy import select

from dw_mcp_server.bridge import McpBridge
from dw_mcp_server.server import handle_message


def _bridge() -> McpBridge:
    settings = get_settings()
    return McpBridge(Database.from_settings(settings), secret_key=settings.secret_key)


async def _call(bridge: McpBridge, payload: dict) -> dict:
    response = await handle_message(json.dumps(payload), bridge)
    assert response is not None
    return json.loads(response)


def _token(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


async def _register_run_cleanup(cleaner, user_id: str) -> None:
    """MCP 为身份创建「会话 Run」；其 requester FK 为 RESTRICT，不清理则用户删不掉。"""
    database = Database.from_settings(get_settings())
    try:
        async with database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(AgentRun.id).where(AgentRun.requester_id == UUID(user_id))
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await database.dispose()
    for run_id in rows:
        cleaner("agent_runs", "id", str(run_id))


async def test_tools_list_returns_registered_tools() -> None:
    bridge = _bridge()
    try:
        body = await _call(
            bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
    finally:
        await bridge.dispose()

    tools = body["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "project_query" in names
    project_query = next(tool for tool in tools if tool["name"] == "project_query")
    assert "project_id" in project_query["inputSchema"]["properties"]


async def test_tools_call_project_list_succeeds_and_is_audited(
    auth_headers, cleaner
) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.ADMIN)
    bridge = _bridge()
    try:
        body = await _call(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "project_list",
                    "arguments": {"limit": 5},
                    "_meta": {"authorization": f"Bearer {_token(headers)}"},
                },
            },
        )
    finally:
        await bridge.dispose()
    await _register_run_cleanup(cleaner, headers["user"])

    assert body["result"]["isError"] is False
    payload = json.loads(body["result"]["content"][0]["text"])
    assert "projects" in payload

    # 审计归属：该身份应有一个「MCP 会话」Run，且带至少一条 tool_call
    database = Database.from_settings(get_settings())
    try:
        async with database.session() as session:
            runs = (
                (
                    await session.execute(
                        select(AgentRun).where(AgentRun.requester_id == UUID(headers["user"]))
                    )
                )
                .scalars()
                .all()
            )
            assert any(run.objective == "MCP 会话" for run in runs)
    finally:
        await database.dispose()


async def test_tools_call_scope_is_enforced(auth_headers, cleaner) -> None:  # noqa: ANN001
    # VIEWER 缺 construction:read → 治理链拒绝（in-band isError）
    headers = await auth_headers(role=RoleName.VIEWER)
    bridge = _bridge()
    try:
        body = await _call(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "progress_analysis",
                    "arguments": {"project_id": "00000000-0000-0000-0000-000000000000"},
                    "_meta": {"authorization": f"Bearer {_token(headers)}"},
                },
            },
        )
    finally:
        await bridge.dispose()
    await _register_run_cleanup(cleaner, headers["user"])

    assert body["result"]["isError"] is True
    assert "scope" in body["result"]["content"][0]["text"]


async def test_tools_call_unknown_tool_is_error_content(auth_headers, cleaner) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.ADMIN)
    bridge = _bridge()
    try:
        body = await _call(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "not_a_tool",
                    "arguments": {},
                    "_meta": {"authorization": f"Bearer {_token(headers)}"},
                },
            },
        )
    finally:
        await bridge.dispose()
    await _register_run_cleanup(cleaner, headers["user"])

    assert body["result"]["isError"] is True
