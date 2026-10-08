"""HTTP 横切中间件 —— request_id / 访问日志 / 安全响应头。

实现选择：**纯 ASGI 中间件，不用 `BaseHTTPMiddleware`**。
原因是 Phase 3 起需要 SSE 流式响应（`GET /runs/{id}/stream`），
而 `BaseHTTPMiddleware` 会把响应完整缓冲后才转发，从而破坏流式。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from dw_infrastructure.logging_setup import bound_request_id
from dw_infrastructure.observability import SpanKind, start_span
from dw_schemas.envelope import REQUEST_ID_HEADER
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("dw_api.request")

MessageSender = Callable[[Message], Awaitable[None]]

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _request_id_from_scope(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == REQUEST_ID_HEADER.lower().encode():
            decoded = value.decode().strip()
            if decoded:
                # 防止外部把超长串灌进来污染日志系统
                return decoded[:64]
            break
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """绑定 request_id、记录访问日志、回写 X-Request-ID 响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # websocket / lifespan 不参与 HTTP 上下文
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        started = time.perf_counter()
        captured_status = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal captured_status
            if message["type"] == "http.response.start":
                captured_status = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                headers.append(
                    (
                        b"x-process-time-ms",
                        f"{(time.perf_counter() - started) * 1000:.2f}".encode(),
                    )
                )
            await send(message)

        with bound_request_id(request_id):
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                logger.info(
                    "request completed",
                    extra={
                        "http_method": scope.get("method", "-"),
                        "http_path": scope.get("path", "-"),
                        "http_status": captured_status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )


class TracingMiddleware:
    """为每个 HTTP 请求开一个 SERVER span（手写 ASGI，不缓冲响应，保 SSE）。

    span 存活期间 `bind_trace_context` 已生效，因此该请求链路上所有日志都带同一个
    `trace_id` —— 日志与 trace 可互相定位。未启用追踪时为 no-op，行为零差异。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        captured_status = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal captured_status
            if message["type"] == "http.response.start":
                captured_status = message["status"]
            await send(message)

        attributes = {
            "http.request.method": scope.get("method", "-"),
            "url.path": scope.get("path", "-"),
        }
        with start_span("http.request", attributes=attributes, kind=SpanKind.SERVER) as span:
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                # 状态码要等响应开始才可知，因此在出口统一回填
                span.set_attribute("http.response.status_code", captured_status)


class SecurityHeadersMiddleware:
    """统一注入安全响应头（需求文档 §13）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {key.lower() for key, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower().encode() not in existing:
                        headers.append((name.encode(), value.encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)
