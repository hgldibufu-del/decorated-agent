"""OpenTelemetry 链路追踪 —— Phase 9。

设计要点：

* **默认零副作用**：只有「显式注入 exporter」（测试）或「`OTEL_ENABLED=true` 且配了
  OTLP 端点」时才装配 `TracerProvider`；否则所有 span 都是 API 层的 no-op，
  启动、测试与接入前完全一致。
* **与既有日志打通**：span 生效期间把 trace_id 写进 `logging_setup.trace_id_var`，
  而 `JsonFormatter` 早已输出该字段 —— 于是「一条日志 ↔ 一条 trace」可直接互查。
* **属性脱敏**：所有 span 属性经 `logging_setup.redact()`，绝不把密钥写进 trace。
* **不注册全局 provider**：`opentelemetry.trace.set_tracer_provider` 一个进程只能设一次，
  会让测试无法反复 configure/reset。这里内部持有 provider 引用作为唯一事实源；
  将来若要接入第三方自动埋点，再在此处补注册。
* 导出用 `SimpleSpanProcessor`（同步、无后台线程）：行为可预测，测试里 span 立即可见。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

from dw_infrastructure.config import Settings
from dw_infrastructure.logging_setup import redact, trace_id_var

logger = logging.getLogger(__name__)

DEFAULT_TRACER_NAME = "dw"


# 追踪状态（进程内单例，测试可反复 configure / reset）
_provider: TracerProvider | None = None


def is_tracing_enabled() -> bool:
    """是否已装配 TracerProvider（未装配时 span 全部为 no-op）。"""
    return _provider is not None


def configure_tracing(
    settings: Settings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    sampler_ratio: float | None = None,
) -> TracerProvider | None:
    """装配追踪。优先级：

    1. 显式传入 `span_exporter`（测试用 `InMemorySpanExporter`）→ 直接装配；
    2. `settings.otel_enabled` 且配置了 OTLP 端点 → 装配并用 OTLP 导出；
    3. 其余 → **不装配**（返回当前状态，不改动任何东西）。

    返回当前生效的 provider（未启用时为 None）。
    """
    global _provider

    if span_exporter is None:
        if settings is None or not settings.otel_enabled:
            return _provider
        endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
        if not endpoint:
            logger.warning(
                "OTEL_ENABLED 已开启但未配置 OTEL_EXPORTER_OTLP_ENDPOINT，跳过追踪装配"
            )
            return _provider
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:  # pragma: no cover - 仅在缺 extras 时触发
            logger.warning(
                "未安装 opentelemetry-exporter-otlp，追踪已启用但不会导出；"
                '请安装 extras：pip install "dw-infrastructure[otel]"'
            )
            return _provider
        span_exporter = OTLPSpanExporter(endpoint=endpoint)

    ratio = settings.otel_trace_sample_ratio if settings is not None else 1.0
    if sampler_ratio is not None:
        ratio = sampler_ratio
    sampler = ALWAYS_ON if ratio >= 1.0 else ParentBased(TraceIdRatioBased(ratio))

    service_name = "dw"
    service_version = "0.1.0"
    environment = "unknown"
    if settings is not None:
        service_name = settings.otel_service_name or settings.service_name
        service_version = settings.app_version
        environment = settings.app_env.value

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment": environment,
            }
        ),
        sampler=sampler,
    )
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    _provider = provider
    logger.info("tracing configured", extra={"service_name": service_name, "sample_ratio": ratio})
    return provider


def reset_tracing() -> None:
    """释放 provider 并回到 no-op（测试清理用）。"""
    global _provider
    if _provider is not None:
        _provider.shutdown()
    _provider = None


def get_tracer(name: str = DEFAULT_TRACER_NAME) -> Tracer:
    """取 tracer。未装配时返回 API 默认的 no-op tracer。"""
    if _provider is not None:
        return _provider.get_tracer(name)
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """当前 span 的 trace_id（无有效 span 时为 None）。"""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


@contextmanager
def bind_trace_context() -> Iterator[str | None]:
    """把当前 trace_id 绑定到日志上下文，并在退出时还原。

    这是「日志 ↔ trace 打通」的唯一入口：`JsonFormatter` 会自动输出该字段。
    """
    trace_id = current_trace_id()
    token = trace_id_var.set(trace_id) if trace_id else None
    try:
        yield trace_id
    finally:
        if token is not None:
            trace_id_var.reset(token)


def set_attributes(span: Span, attributes: Mapping[str, Any] | None) -> None:
    """批量写 span 属性：先脱敏；非标量转字符串（OTel 只接受标量/同构列表）。"""
    if not attributes:
        return
    for key, value in redact(dict(attributes)).items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, str(value))


def record_ok(span: Span) -> None:
    span.set_status(Status(StatusCode.OK))


def record_error(span: Span, error: BaseException) -> None:
    """记录异常：写入 span event + 置 ERROR 状态（message 截断，避免超长）。"""
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, str(error)[:200]))


@contextmanager
def start_span(
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    tracer_name: str = DEFAULT_TRACER_NAME,
) -> Iterator[Span]:
    """开一个 span，并在其生命周期内把 trace_id 绑进日志上下文。

    未装配追踪时同样是安全可用的（no-op span），调用方无需分支判断。
    """
    tracer = get_tracer(tracer_name)
    with tracer.start_as_current_span(name, kind=kind) as span:
        set_attributes(span, attributes)
        with bind_trace_context():
            yield span
