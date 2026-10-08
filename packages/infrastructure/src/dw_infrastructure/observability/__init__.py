"""可观测适配层 —— Phase 9。

对外只暴露追踪门面；调用方通过 `start_span` / `record_ok` / `record_error` 使用，
不直接接触 OpenTelemetry SDK，便于将来替换或增补（如 metrics）。
"""

from dw_infrastructure.observability.tracing import (
    DEFAULT_TRACER_NAME,
    bind_trace_context,
    configure_tracing,
    current_trace_id,
    get_tracer,
    is_tracing_enabled,
    record_error,
    record_ok,
    reset_tracing,
    set_attributes,
    start_span,
)
from opentelemetry.trace import Span, SpanKind

__all__ = [
    "DEFAULT_TRACER_NAME",
    "Span",
    "SpanKind",
    "bind_trace_context",
    "configure_tracing",
    "current_trace_id",
    "get_tracer",
    "is_tracing_enabled",
    "record_error",
    "record_ok",
    "reset_tracing",
    "set_attributes",
    "start_span",
]
