"""可观测与评估集成测试 —— Phase 9（需要真实 PostgreSQL + pgvector）。

覆盖三件事：

1. HTTP 请求 → 产出 `http.request` SERVER span（带真实状态码与路径）；
2. 一次真实 Run → 产出 `run.execute_plan` span 及其同 trace 的 `tool.call` 子 span；
3. golden set 评估 → 检索指标不低于阈值（**检索质量回归闸门**）。

追踪用 `InMemorySpanExporter` 注入，不注册全局 provider（见 tracing.py 的设计说明），
因此不影响其它用例；每个用例结束都 `reset_tracing()`。
"""

from __future__ import annotations

from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_infrastructure.evaluation import evaluate_default
from dw_infrastructure.observability import configure_tracing, reset_tracing
from dw_infrastructure.rag.embeddings import build_embedder
from dw_infrastructure.rag.store import DocumentStore
from dw_schemas.iam import RoleName
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind


async def test_http_request_produces_server_span(client):
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    try:
        response = client.get("/api/v1/live")
        assert response.status_code == 200

        spans = [span for span in exporter.get_finished_spans() if span.name == "http.request"]
        assert spans, "HTTP 请求应产出 http.request span"
        span = spans[-1]
        assert span.kind is SpanKind.SERVER
        assert span.attributes["http.request.method"] == "GET"
        assert span.attributes["url.path"] == "/api/v1/live"
        assert span.attributes["http.response.status_code"] == 200
    finally:
        reset_tracing()


async def test_run_produces_run_and_tool_spans(client, auth_headers, make_project, cleaner):
    """Run span 与其内部 tool span 必须属于同一条 trace（父子可追溯）。"""
    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    try:
        headers = await auth_headers(role=RoleName.PROJECT_MANAGER)
        await make_project(owner_id=headers["user"])
        await make_project(owner_id=headers["user"])

        created = client.post(
            "/api/v1/runs",
            headers=headers,
            json={"intent": "project_overview", "objective": "看全部项目概览"},
        )
        assert created.status_code == 201, created.text
        cleaner("agent_runs", "id", created.json()["id"])

        finished = exporter.get_finished_spans()
        run_spans = [span for span in finished if span.name == "run.execute_plan"]
        assert run_spans, "应产出 run.execute_plan span"
        run_span = run_spans[0]
        assert run_span.attributes["run.intent"] == "project_overview"
        assert run_span.attributes["run.status"] == "completed"
        assert run_span.attributes["run.review_decision"] == "PASS"

        tool_spans = [span for span in finished if span.name == "tool.call"]
        assert tool_spans, "Run 内应产出 tool.call span"
        assert all(span.attributes["tool.status"] == "success" for span in tool_spans)
        for span in tool_spans:
            assert span.context.trace_id == run_span.context.trace_id
    finally:
        reset_tracing()


async def test_retrieval_evaluation_meets_quality_floor():
    """检索质量回归闸门：golden set 指标低于阈值即失败。

    数据集与指标都是确定性的（FakeEmbedder + 纯函数指标），因此阈值可作硬约束。
    """
    settings = get_settings()
    database = Database.from_settings(settings)
    try:
        async with database.session() as session:
            store = DocumentStore(
                session, build_embedder(settings), settings.rag_embedding_dim
            )
            report = await evaluate_default(store)
    finally:
        await database.dispose()

    metrics = report.metrics
    assert metrics.cases == 8
    # 实测基线：hit/recall/mrr = 1.0，precision = 0.333；阈值留出「最多 1 例退化」的余量
    assert metrics.hit_at_k >= 0.875, report.as_dict()
    assert metrics.recall_at_k >= 0.875, report.as_dict()
    assert metrics.mrr >= 0.875, report.as_dict()
    assert metrics.precision_at_k >= 0.3, report.as_dict()
