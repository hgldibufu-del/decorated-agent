# Phase 9 Gate 报告（可观测与评估）

> 结论：**PASS**。OpenTelemetry 链路追踪真实接入（默认零副作用），确定性评估 harness 落地并成为检索质量回归闸门。
> 日期：2026-10-05
> 范围：三个平台课题的第 2 个（MCP → **可观测** → Mem0）。Langfuse / RAGAS 明确不做硬依赖，只留协议接缝。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| 追踪门面 | `packages/infrastructure/.../observability/tracing.py`：`configure_tracing` / `get_tracer` / `start_span` / `bind_trace_context` / `set_attributes` / `record_ok` / `record_error` / `reset_tracing`；`observability/__init__.py` 只重导出门面（含 `Span` / `SpanKind`），上层不直接依赖 OTel SDK |
| 依赖 | `opentelemetry-api` + `opentelemetry-sdk`（基础依赖）；`opentelemetry-exporter-otlp` 为可选 extra `dw-infrastructure[otel]` |
| 配置 | `Settings` 新增 `otel_enabled`（默认 `false`）/ `otel_exporter_otlp_endpoint` / `otel_service_name` / `otel_trace_sample_ratio` |
| 探针 | `http.request`（`TracingMiddleware`，纯 ASGI）、`run.execute_plan` / `run.execute` / `run.resume`（`RunService`）、`tool.call`（`ToolExecutor` 治理链入口，**含拒绝路径**）、`rag.retrieve`（混合检索入口） |
| 日志打通 | `start_span` 生命周期内绑定 `trace_id_var` → `JsonFormatter` 自动输出 `trace_id`。**日志 ↔ trace 可互查** |
| 评估 harness | `packages/infrastructure/.../evaluation/`：`metrics.py`（纯函数指标）、`golden.py`（加载 + 校验）、`runner.py`（隔离摄入 + 逐案打分 + 清理）、`__main__.py`（CLI） |
| 数据集 | `evaluation/datasets/aftersales_golden.json`（8 文档 / 8 用例，k=3），作为包数据随分发包提供 |
| 回归闸门 | `tests/integration/test_observability.py` 断言 `hit/recall/MRR ≥ 0.875`、`precision ≥ 0.3` |

---

## 2. 测试与质量

- **单元测试**：新增 `test_tracing.py`（7 例：默认 no-op、属性脱敏、父子 span 同 trace、context 还原、异常记录、**日志 trace_id == span trace_id** 契约、未启用时 `configure_tracing` 返回 None 且不产生副作用）；新增 `test_eval_metrics.py`（10 例：四个指标边界、宏平均、内置 golden set 有效性、非法数据集报错）。
- **集成测试**：新增 `test_observability.py`（3 例）：HTTP 请求 → `http.request` SERVER span（含真实状态码）；真实 Run → `run.execute_plan` span（`run.status=completed`、`review_decision=PASS`）与其同 trace 的 `tool.call` span；golden set 评估达标。
- **全量结果**：`pytest tests/` **330 passed**（单元 201 / 集成 109 / API 契约 20），零失败；`read_lints` 零 error/warning。本阶段新增 **20 个用例**（单元 17 + 集成 3）。
  注：Phase 7 Gate 报告记录的全量为 285 passed，与本轮 330 的口径不完全一致（同一命令、同一目录），此处以本轮实测为准。
- **依赖验证**：`opentelemetry-sdk 1.45.0` 可正常安装与导入；未装配时 `trace.get_tracer()` 为 ProxyTracer（no-op）。

---

## 3. Definition of Done 核对

- [x] `configure_tracing` 可装配；**未配置端点时零副作用**（既有用例全绿，即无行为漂移）。
- [x] Tool / Run / HTTP / RAG 四类 span 落地；span 属性经 `redact()` 脱敏。
- [x] 日志中的 `trace_id` 与 span 的 trace_id 一致（单测断言）。
- [x] 评估 harness 可跑出确定性报告（hit@k / recall@k / precision@k / MRR），并有 pytest 阈值回归。
- [x] 全量测试 330 passed；`read_lints` 零错误。
- [x] 文档更新：`docs/observability.md`（新增）、`architecture.md`（§1 状态 / §6 日志 / §8 落位）、`README`（相位表 / 技术栈 / 环境变量 / seed 表 / 测试章节）+ 本报告。

---

## 4. 实测结果

```
$ py -3 -m pytest tests/ -q
330 passed in 68.08s

$ py -3 -m dw_infrastructure.evaluation
{ "dataset": "aftersales-golden-v1", "k": 3, "ingested_documents": 8,
  "metrics": {"hit_at_k": 1.0, "recall_at_k": 1.0, "precision_at_k": 0.3333, "mrr": 1.0, "cases": 8} }
```

阈值据此定为 `hit / recall / MRR ≥ 0.875`、`precision ≥ 0.3`（实测全为 1.0 / 0.333，留「最多 1 例退化」余量）。

---

## 5. 关键设计决策（落地记录）

1. **默认零副作用**：未启用时 span 全为 no-op。这是「加可观测」与「改行为」的边界 —— 接入追踪不应让任何既有测试变色。
2. **不注册全局 provider**：`set_tracer_provider` 一个进程只能设一次，会让测试无法反复 configure/reset；门面自持 provider 引用，测试可完全隔离。
3. **langfuse / RAGAS 不做硬依赖**：二者要么需外部服务与 Key，要么需 LLM 判官（非确定性），无法离线验证。改为协议接缝 —— Langfuse 走标准 OTLP 端点（**代码零改动**），RAGAS 只需替换 `metrics.py` 的实现。
4. **`tool.call` 包在治理链入口**：被拒绝的调用也会留 span（`tool.status=error`），权限问题在 trace 上直接可见，而不只躺在审计表里。
5. **Run 终态属性后填**：Run 结局在 `_finalize` 之后才定稿，所以属性在状态定稿后回填；一开始就塞会写出假数据。
6. **评估隔离用 source 前缀**：不依赖也不破坏库内既有数据，`precision` 不被无关文档稀释，跑完即清理。
7. **指标全为纯函数**：可离线复现、可作硬阈值回归；与「LLM 判官」类指标严格分工。

---

## 6. 非目标（明确未做）

- Langfuse / RAGAS 的真实接入（留接缝，理由见 §5.3）。
- LLM-as-judge 类主观评估、真实语义嵌入（仍用 FakeEmbedder 保持确定性）。
- 日志采集/存储栈（ELK / Loki）、Grafana 面板、告警规则与 on-call 流程。
- Prometheus `/metrics`（RED 指标）—— 本轮范围外（用户在范围选项中未勾选）。
- Tail-based sampling、`traceparent` 跨进程透传、采样策略调优。

---

## 7. 平台课题全景（累计）

| 课题 | 状态 | 交付位置 |
|------|------|----------|
| MCP 传输层 | ✅ | `apps/mcp-server`（stdio JSON-RPC 子集，零第三方依赖） |
| 可观测与评估 | ✅ | `packages/infrastructure/observability` + `.../evaluation` |
| 记忆层（Mem0） | ⏳ 未开始 | — |

---

## 8. 下一步建议

- **记忆层（Mem0）**：长期用户偏好 / 项目上下文，供四个 Specialist 复用（三个平台课题的第 3 个）。
- 若要先做小切口：把 `SimpleSpanProcessor` 换为 `BatchSpanProcessor` 并接一个本地 OTLP 采集端，
  或在 `git` 之外的 CI 里把评估阈值纳入流水线（当前已可由 `pytest tests/integration/test_observability.py` 触发）。
