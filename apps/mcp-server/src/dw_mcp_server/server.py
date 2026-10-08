"""MCP stdio 服务：按行读 JSON-RPC → 分发 → 写单行响应。

刻意保持**薄**：协议细节在 `protocol.py`，工具桥接在 `bridge.py`，这里只做「解析 → 分发 → 序列化」。
"""

from __future__ import annotations

import json
from typing import IO, Any

from dw_domain.errors import ToolError

from dw_mcp_server.bridge import McpBridge
from dw_mcp_server.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    UNAUTHORIZED,
    McpAuthError,
    McpProtocolError,
    dumps,
    error_response,
    initialize_result,
    result_response,
    tool_error_content,
    tool_text_content,
)


async def handle_message(raw: str, bridge: McpBridge) -> str | None:
    """处理一行 JSON-RPC，返回一行响应；通知（无 id）返回 None。"""
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return dumps(error_response(None, PARSE_ERROR, "JSON 解析失败"))
    if not isinstance(message, dict):
        return dumps(error_response(None, INVALID_REQUEST, "请求必须是 JSON 对象"))

    method = message.get("method")
    request_id = message.get("id")
    raw_params = message.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    is_notification = "id" not in message

    if not isinstance(method, str):
        if is_notification:
            return None
        return dumps(error_response(request_id, INVALID_REQUEST, "缺少 method"))

    # 通知不回响应（含 notifications/initialized）
    if is_notification:
        return None

    try:
        result = await _dispatch(method, params, bridge)
    except McpAuthError as exc:
        return dumps(error_response(request_id, UNAUTHORIZED, str(exc)))
    except McpProtocolError as exc:
        return dumps(error_response(request_id, exc.code, str(exc)))
    except ToolError as exc:
        # 工具治理错误（未注册 / 缺 scope / 入参非法…）：按 MCP 语义 in-band 返回
        return dumps(result_response(request_id, tool_error_content(str(exc))))
    except Exception as exc:  # 绝不静默：兜底为内部错误并带上异常类型，便于定位
        return dumps(
            error_response(
                request_id, INTERNAL_ERROR, f"服务内部错误: {type(exc).__name__}: {exc}"
            )
        )
    return dumps(result_response(request_id, result))


async def _dispatch(method: str, params: dict[str, Any], bridge: McpBridge) -> dict[str, Any]:
    if method == "initialize":
        return initialize_result()
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": await bridge.list_tools()}
    if method == "tools/call":
        return await _call_tool(params, bridge)
    raise McpProtocolError(METHOD_NOT_FOUND, f"不支持的方法: {method}")


async def _call_tool(params: dict[str, Any], bridge: McpBridge) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise McpProtocolError(INVALID_PARAMS, "tools/call 缺少 name")

    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise McpProtocolError(INVALID_PARAMS, "arguments 必须是对象")

    actor = bridge.resolve_actor(params.get("_meta"))
    output = await bridge.call_tool(name, arguments, actor)
    return tool_text_content(output)


async def serve(stdin: IO[str], stdout: IO[str], bridge: McpBridge) -> None:
    """stdin/stdout 按行收发；stdout 只写协议帧（日志一律走 stderr）。"""
    while True:
        line = stdin.readline()
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        response = await handle_message(stripped, bridge)
        if response is not None:
            stdout.write(response + "\n")
            stdout.flush()
