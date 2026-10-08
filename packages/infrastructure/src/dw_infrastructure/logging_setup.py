"""结构化日志 + request_id 上下文 + 敏感信息脱敏 —— 需求文档 §17。

要求：
* 单行 JSON 输出，可被 ELK / Loki 直接采集；
* `request_id` 贯穿日志（并透传给错误信封与 Trace）；
* 禁止记录 API Key / 密码 / Token：Key 名命中敏感词的值统一替换为 ***REDACTED***。

注意：脱敏是对「结构化 extra 字段」做的强保证。业务代码仍不应把密钥拼进 message 字符串。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

REDACTED: str = "***REDACTED***"

_SENSITIVE_KEY_RE = re.compile(
    r"api[-_]?key|secret|password|passwd|token|authorization|credential|private[-_]?key",
    re.IGNORECASE,
)

# 日志中属于 stdlib LogRecord 的保留字段，不应作为业务 extra 输出
_RESERVED_LOG_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def _redact_field(key: str, value: Any) -> Any:
    """字段级脱敏：键名命中敏感词时整值替换，否则递归处理嵌套结构。"""
    if _SENSITIVE_KEY_RE.search(key):
        return REDACTED
    return redact(value)


def redact(value: Any) -> Any:
    """递归脱敏：命中敏感词的 dict key 会被整值替换，支持嵌套结构与 list。"""
    if isinstance(value, Mapping):
        return {
            key: _redact_field(key, item) if isinstance(key, str) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


@contextmanager
def bound_request_id(request_id: str) -> Iterator[str]:
    """把 request_id 绑定到当前上下文（含 async task 隔离）。"""
    token = request_id_var.set(request_id)
    try:
        yield request_id
    finally:
        request_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    """输出单行 JSON，附加 request_id 与已脱敏的 extra 字段。"""

    def __init__(self, *, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self._service_name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }

        trace_id = trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_KEYS or key.startswith("_"):
                continue
            payload[key] = _redact_field(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    """人类可读格式，便于本地开发时肉眼排查。"""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")


def configure_logging(
    *,
    level: str = "INFO",
    json_format: bool = True,
    service_name: str = "dw-api",
    stream: Any = None,
) -> logging.Handler:
    """配置根 logger。返回安装好的 handler，便于测试精确清理。"""
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(
        JsonFormatter(service_name=service_name) if json_format else PlainFormatter()
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 第三方库日志噪声收敛
    logging.getLogger("uvicorn.access").handlers = []
    return handler


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
