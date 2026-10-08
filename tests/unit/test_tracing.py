"""OpenTelemetry 追踪单测 —— Phase 9。

覆盖：默认 no-op、span 导出与属性脱敏、父子关系、异常记录，
以及**核心契约**「日志里的 trace_id 与 span 的 trace_id 完全一致」。
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from dw_infrastructure.config import Settings
from dw_infrastructure.logging_setup import REDACTED, configure_logging, trace_id_var
from dw_infrastructure.observability import (
    configure_tracing,
    current_trace_id,
    is_tracing_enabled,
    record_error,
    record_ok,
    reset_tracing,
    start_span,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


@pytest.fixture(autouse=True)
def _clean_tracing():
    reset_tracing()
    yield
    reset_tracing()


def _install_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    return exporter


def test_tracing_is_disabled_by_default():
    assert is_tracing_enabled() is False
    # 未开启 otel_enabled 时不装配（返回 None），不产生任何副作用
    assert configure_tracing(Settings(app_env="testing")) is None
    assert is_tracing_enabled() is False


def test_span_is_noop_when_not_configured():
    with start_span("tool.call", attributes={"tool.id": "x"}) as span:
        assert is_tracing_enabled() is False
        assert current_trace_id() is None
        assert trace_id_var.get() is None
        span.set_attribute("anything", 1)  # 不应抛错


def test_span_is_exported_with_redacted_attributes():
    exporter = _install_exporter()
    with start_span(
        "tool.call",
        attributes={"tool.id": "project_query", "api_key": "sk-should-not-leak"},
    ) as span:
        span.set_attribute("tool.attempt", 2)
        record_ok(span)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    finished = spans[0]
    assert finished.name == "tool.call"
    assert finished.attributes["tool.id"] == "project_query"
    assert finished.attributes["tool.attempt"] == 2
    # 敏感字段脱敏后才写入 trace，绝不泄漏原始值
    assert finished.attributes["api_key"] == REDACTED
    assert finished.status.status_code is StatusCode.OK


def test_parent_child_spans_share_trace_id():
    exporter = _install_exporter()
    with start_span("run.execute_plan") as parent:
        parent_trace_id = current_trace_id()
        with start_span("tool.call"):
            assert current_trace_id() == parent_trace_id

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["tool.call"].context.trace_id == spans["run.execute_plan"].context.trace_id
    assert spans["tool.call"].parent.span_id == spans["run.execute_plan"].context.span_id


def test_trace_context_is_restored_after_span():
    _install_exporter()
    assert trace_id_var.get() is None
    with start_span("x"):
        assert trace_id_var.get() is not None
    assert trace_id_var.get() is None


def test_record_error_marks_status_and_adds_event():
    exporter = _install_exporter()
    with start_span("tool.call") as span:
        record_error(span, ValueError("boom"))

    finished = exporter.get_finished_spans()[0]
    assert finished.status.status_code is StatusCode.ERROR
    assert "boom" in (finished.status.description or "")
    assert [event.name for event in finished.events] == ["exception"]


def test_json_log_carries_trace_id_of_current_span():
    """核心契约：日志的 trace_id == span 的 trace_id（日志与 trace 可互查）。"""
    exporter = _install_exporter()
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    stream = io.StringIO()
    configure_logging(
        level="INFO", json_format=True, service_name="dw-test", stream=stream
    )
    try:
        with start_span("http.request"):
            logging.getLogger("dw.test").warning("hello")
        payload = json.loads(stream.getvalue().strip().splitlines()[-1])
        expected = format(exporter.get_finished_spans()[0].context.trace_id, "032x")
        assert payload["trace_id"] == expected
        assert payload["request_id"] == "-"
    finally:
        for existing in list(root.handlers):
            root.removeHandler(existing)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
