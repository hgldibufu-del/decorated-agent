"""MCP / JSON-RPC 2.0 协议子集 —— 纯数据结构与响应构造（不碰 IO、不碰 DB）。

只实现跨进程工具调用所需的最小方法集：
`initialize` / `ping` / `tools/list` / `tools/call`（另识别 `notifications/initialized`，无响应）。

线格式：**每行一个 JSON 对象**（MCP stdio 传输约定），stdout 仅承载协议帧。
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "dw-mcp-server"

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# 应用层：鉴权失败（MCP 未约定标准码，取 -32000 区间的应用自定义码）
UNAUTHORIZED = -32001


class McpProtocolError(Exception):
    """协议级错误：由 `handle_message` 转成 JSON-RPC error 响应。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


class McpAuthError(Exception):
    """鉴权失败（缺少 / 无效令牌）。"""


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def dumps(message: dict[str, Any]) -> str:
    """序列化为单行 JSON（协议要求帧内不得含裸换行）。"""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
    }


def tool_text_content(payload: Any) -> dict[str, Any]:
    """成功结果：把工具输出序列化为 MCP content 文本块。"""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def tool_error_content(message: str) -> dict[str, Any]:
    """工具执行失败：按 MCP 语义放在 result 里（isError=true），而不是协议层错误。"""
    return {"content": [{"type": "text", "text": message}], "isError": True}


def extract_bearer(value: Any) -> str | None:
    """从 `_meta.authorization` 之类的字段提取 Bearer 令牌。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip() or None
    return text
