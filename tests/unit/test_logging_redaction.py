"""日志脱敏与 request_id 上下文单测 —— 需求文档 §17。

需求明确要求：禁止记录 API Key / 密码 / 完整敏感信息。
这里验证的是「即使有人误把密钥塞进 extra，出口也已经被改写」。
"""

from __future__ import annotations

import io
import json
import logging

from dw_infrastructure.logging_setup import (
    REDACTED,
    JsonFormatter,
    configure_logging,
    redact,
    request_id_var,
)


def _emit(record_kwargs: dict, extra: dict) -> dict:
    formatter = JsonFormatter(service_name="dw-test")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(formatter.format(record))


def test_sensitive_keys_are_redacted():
    payload = redact(
        {
            "api_key": "sk-secret",
            "llm_api_key": "sk-secret",
            "password": "123456",
            "access_token": "abc",
            "Authorization": "Bearer x",
            "normal_field": "keep-me",
        }
    )
    assert payload["normal_field"] == "keep-me"
    assert REDACTED in {payload["api_key"], payload["llm_api_key"], payload["password"]}
    assert payload["password"] == REDACTED


def test_redaction_is_recursive():
    payload = redact({"database": {"password": "p1", "host": "db"}, "items": [{"token": "t"}]})
    assert payload["database"]["password"] == REDACTED
    assert payload["database"]["host"] == "db"
    assert payload["items"][0]["token"] == REDACTED


def test_plain_values_pass_through():
    assert redact(42) == 42
    assert redact("keep") == "keep"
    assert redact(None) is None


def test_formatter_injects_request_id_and_redacts_extra():
    with _request_id("rid-1"):
        payload = _emit({}, {"api_key": "sk-secret", "component": "postgres"})
    assert payload["request_id"] == "rid-1"
    assert payload["component"] == "postgres"
    assert payload["api_key"] == REDACTED


def test_formatter_excludes_reserved_logrecord_fields():
    """LogRecord 内部字段不得重复出现在输出里（msg 例外，它是格式化后的消息）。"""
    with _request_id("-"):
        payload = _emit({}, {"custom": 1})
    for reserved in ("args", "pathname", "exc_text", "stack_info", "lineno"):
        assert reserved not in payload
    assert payload["msg"] == "hello"
    assert payload["custom"] == 1


def test_configure_logging_emits_json():
    stream = io.StringIO()
    configure_logging(level="INFO", json_format=True, service_name="dw-test", stream=stream)
    logging.getLogger("spec.case").info("structured", extra={"password": "p"})
    payload = json.loads(stream.getvalue().strip())
    assert payload["service"] == "dw-test"
    assert payload["password"] == REDACTED
    assert payload["request_id"] == "-"
    logging.getLogger().handlers.clear()


class _request_id:
    """极简上下文包装，避免测试依赖 conftest。"""

    def __init__(self, value: str) -> None:
        self._value = value

    def __enter__(self):
        self._token = request_id_var.set(self._value)
        return self._value

    def __exit__(self, *exc):
        request_id_var.reset(self._token)
        return False
