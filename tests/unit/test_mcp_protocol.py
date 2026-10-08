"""MCP 协议层单测（不依赖 DB）：初始化 / 通知 / 错误码 / 令牌提取 / 工具描述。"""

from __future__ import annotations

import json

from dw_agent_runtime.registry import ToolSpec
from dw_agent_runtime.tools import BUILTIN_TOOLS
from dw_schemas.agent import RiskLevel

from dw_mcp_server.bridge import McpBridge, tool_descriptor
from dw_mcp_server.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    UNAUTHORIZED,
    extract_bearer,
)
from dw_mcp_server.server import handle_message


def _bridge() -> McpBridge:
    # 协议单测不访问数据库；database 传占位对象即可
    return McpBridge(None, secret_key="unit-secret")  # type: ignore[arg-type]


async def _call(payload: object) -> dict:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    response = await handle_message(raw, _bridge())
    assert response is not None
    return json.loads(response)


async def test_initialize_returns_protocol_and_server_info() -> None:
    body = await _call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

    result = body["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["capabilities"]["tools"] is not None
    assert result["serverInfo"]["name"] == "dw-mcp-server"


async def test_ping_returns_empty_result() -> None:
    body = await _call({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert body["result"] == {}


async def test_notification_has_no_response() -> None:
    response = await handle_message(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), _bridge()
    )
    assert response is None


async def test_unknown_method_is_method_not_found() -> None:
    body = await _call({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert body["error"]["code"] == METHOD_NOT_FOUND


async def test_malformed_json_is_parse_error() -> None:
    body = await _call("{not json")
    assert body["error"]["code"] == PARSE_ERROR
    assert body["id"] is None


async def test_tools_call_without_name_is_invalid_params() -> None:
    body = await _call({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}})
    assert body["error"]["code"] == INVALID_PARAMS


async def test_tools_call_without_token_is_unauthorized() -> None:
    body = await _call(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "project_list", "arguments": {}},
        }
    )
    assert body["error"]["code"] == UNAUTHORIZED


def test_extract_bearer_accepts_with_and_without_prefix() -> None:
    assert extract_bearer("Bearer abc") == "abc"
    assert extract_bearer("abc") == "abc"
    assert extract_bearer("   ") is None
    assert extract_bearer(None) is None


def test_tool_descriptor_exposes_input_schema() -> None:
    spec = ToolSpec(
        tool_id="project_query",
        description="按 ID 查询单个项目",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        timeout_ms=5000,
        retry_max_attempts=2,
        retry_backoff_ms=100,
        fallback_tool_id=None,
        idempotency_required=False,
        audit_required=True,
        enabled=True,
    )

    descriptor = tool_descriptor(spec, BUILTIN_TOOLS["project_query"])

    assert descriptor["name"] == "project_query"
    assert descriptor["description"] == "按 ID 查询单个项目"
    assert "project_id" in descriptor["inputSchema"]["properties"]


def test_tool_descriptor_without_definition_falls_back_to_object_schema() -> None:
    spec = ToolSpec(
        tool_id="ghost_tool",
        description="无实现",
        required_scopes=(),
        risk_level=RiskLevel.L0,
        timeout_ms=1000,
        retry_max_attempts=1,
        retry_backoff_ms=0,
        fallback_tool_id=None,
        idempotency_required=False,
        audit_required=False,
        enabled=True,
    )

    descriptor = tool_descriptor(spec, None)

    assert descriptor["inputSchema"] == {"type": "object", "properties": {}}
