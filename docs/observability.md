# 可观测与评估（Observability & Evaluation）

> 对应需求文档 §17（日志与脱敏）、§26（可观测）、Phase 9。
> 本文描述**当前仓库中真实存在的代码**，不含未实现模块。

---

## 1. 两块能力

| 能力 | 位置 | 回答的问题 |
|------|------|------------|
| 链路追踪（OpenTelemetry） | `packages/infrastructure/src/dw_infrastructure/observability/` | 一次请求/一次 Run 到底经过了哪些环节、哪一步慢、哪一步失败 |
| 评估 harness | `packages/infrastructure/src/dw_infrastructure/evaluation/` | 检索出来的证据对不对（可量化、可回归） |

两者与既有的**结构化日志 + 审计表**互补：日志与审计表是「事实记录」，追踪是「因果链」，
评估是「质量水位」。

---

## 2. 设计约束（为什么这样写）

1. **默认零副作用**。只有在「注入 exporter」（测试）或「`OTEL_ENABLED=true` 且配了 OTLP 端点」
   时才装配 `TracerProvider`；否则 `start_span` 拿到的是 no-op span，**启动、测试与接入前完全一致**。
   这让「加可观测」不会变成「改行为」。
2. **不注册全局 provider**。`opentelemetry.trace.set_tracer_provider` 一个进程只能设置一次，
   会让测试无法反复 configure / reset。门面内部持有 provider 引用作为唯一事实源。
   （将来接入第三方自动埋点，再在该处补注册。）
3. **不引入外部服务即可验证**。`opentelemetry-api` + `opentelemetry-sdk` 是硬依赖；
   OTLP 导出器是可选 extra（`dw-infrastructure[otel]`）。Langfuse / RAGAS **不做硬依赖**：
   它们要么需要外部服务与 Key，要么需要 LLM 判官，无法离线确定性验证 —— 一律留**协议接缝**。
4. **脱敏先行**。span 属性统一经 `logging_setup.redact()`，键名命中
   `api[-_]?key|secret|password|token|authorization|credential|private[-_]?key` 的值直接替换为
   `***REDACTED***`，绝不把密钥写进 trace。
5. **手写 ASGI**。追踪中间件仍是纯 ASGI（与 `RequestContextMiddleware` 一致），
   不缓冲响应，避免破坏 `GET /runs/{id}/stream` 这类流式接口。

---

## 3. span 清单（探针落点）

| span 名 | 位置 | 关键属性 |
|---------|------|----------|
| `http.request`（SERVER） | `dw_api/middleware.py::TracingMiddleware` | `http.request.method`、`url.path`、`http.response.status_code` |
| `run.execute_plan` | `RunService.execute_plan` | `run.intent`、`project.count` → `run.id`、`run.status`、`run.review_decision`、`artifact.count` |
| `run.execute` | `RunService.execute`（直连 Agent/Skill） | `agent.id`、`skill.id`、`project.id` → Run 终态同上 |
| `run.resume` | `RunService.resume`（审批后恢复） | `run.id` → Run 终态同上 |
| `tool.call` | `ToolExecutor.call` | `tool.id`、`tool.fallback`、`run.id` → `tool.status`、`tool.attempt`、`tool.duration_ms`、`tool.fallback_used` |
| `rag.retrieve` | `dw_infrastructure/rag/retrieval.py::retrieve` | `rag.k`、`rag.vector_k`、`rag.bm25_k` → `rag.strategy`、`rag.chunk_count` |

约定：

* `tool.call` 包在**治理链入口**上，因此**被拒绝的调用也会留下 span**（`tool.status=error`），
  权限问题在 trace 上直接可见，而不是只体现在审计表里；
* `rag.retrieve` 刻意**不记录 query 原文**（可能含客户敏感信息），只记规模与策略；
* Run 终态属性在 Run 状态定稿后才回填 —— span 一开始无法知道结局，硬塞会写出假数据。

---

## 4. 启用与配置

默认关闭。开启并导出到 OTLP 采集端：

```powershell
# 1) 装可选导出器
.\.venv\Scripts\python.exe -m pip install "dw-infrastructure[otel]"

# 2) 环境变量
$env:OTEL_ENABLED = "true"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
$env:OTEL_SERVICE_NAME = "dw-api"        # 留空回落到 SERVICE_NAME
$env:OTEL_TRACE_SAMPLE_RATIO = "1.0"     # < 1 时 ParentBased + TraceIdRatio
```

| 变量 | 默认 | 说明 |
|------|------|------|
| `OTEL_ENABLED` | `false` | 关闭时全部 span 为 no-op |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | 配了才导出；缺 extras 时只告警，不崩 |
| `OTEL_SERVICE_NAME` | 空 | 留空回落到 `SERVICE_NAME` |
| `OTEL_TRACE_SAMPLE_RATIO` | `1.0` | 采样比例 |

导出使用 `SimpleSpanProcessor`（同步、无后台线程）：行为可预测，测试里 span 立即可见。
生产若需批量导出，可在 `configure_tracing` 内换成 `BatchSpanProcessor`。

---

## 5. 日志 ↔ trace 打通（核心契约）

`logging_setup` 里 `request_id` / `trace_id` 两个 `ContextVar` 早已存在，且 `JsonFormatter`
早已输出 `trace_id` —— Phase 9 补上的只是「谁来填」：`start_span` 在 span 生命周期内
调用 `bind_trace_context()`，把当前 span 的 trace_id 写入该 ContextVar，退出即还原。

因此**一条 JSON 日志可以直接定位到一条 trace**：

```json
{"ts":"...","level":"INFO","logger":"dw_api.request","service":"dw-api",
 "msg":"request completed","request_id":"...","trace_id":"4bf92f3577b34da6a3ce929d0e0e4736",
 "http_status":200,"duration_ms":12.3}
```

由 `tests/unit/test_tracing.py::test_json_log_carries_trace_id_of_current_span` 兜住：
断言日志里的 `trace_id` 与 span 的 `trace_id` **完全一致**。

---

## 6. 评估 harness

### 6.1 golden set

`evaluation/datasets/aftersales_golden.json`：

```json
{
  "name": "aftersales-golden-v1",
  "k": 3,
  "documents": [{"key": "...", "title": "...", "content": "...", "source": "...", "metadata": {}}],
  "cases": [{"query": "...", "relevant": ["<document key>"]}]
}
```

* 用 **JSON** 而非 YAML：不为此引入 PyYAML；
* `relevant` 引用 **document key** 而不是数据库 id —— 语料可在任意环境重新摄入而指标不变；
* 加载即校验：引用不存在的 key、或 documents/cases 为空，**直接报错**，不静默算错。

### 6.2 指标（纯函数）

| 指标 | 定义 |
|------|------|
| `hit@k` | top-k 是否命中至少一个相关项（1/0） |
| `recall@k` | top-k 覆盖了多少比例的相关项 |
| `precision@k` | top-k 中相关项占比 |
| `MRR` | 第一个相关项排名倒数 |

数据集级取**宏平均**（每案等权），避免长尾用例被大用例稀释。

### 6.3 隔离策略

摄入 golden 语料时给 `source` 加本次运行独有前缀，评估时只认同前缀命中、并剥掉前缀比对 key：

* 不依赖、也不破坏库里既有数据；
* `precision` 不被无关文档稀释；
* 默认跑完即清理（失败也清理），不给库留垃圾。

### 6.4 运行方式

```powershell
# CI 回归闸门（确定性阈值）
.\.venv\Scripts\python.exe -m pytest tests/integration/test_observability.py -q

# 单独跑评估，输出 JSON（汇总 + 逐案明细）
.\.venv\Scripts\python.exe -m dw_infrastructure.evaluation
.\.venv\Scripts\python.exe -m dw_infrastructure.evaluation path/to/other_golden.json
```

---

## 7. Langfuse / RAGAS 接缝

本阶段**不引入**：前者需外部服务与 Key，后者的语义指标（answer relevancy / faithfulness）
依赖 LLM 判官、非确定性，无法离线验证。接缝位置：

| 想接的能力 | 接缝 | 替换成本 |
|------------|------|----------|
| Langfuse（trace 汇聚/看板） | 已产出标准 OTel span —— 直接配 OTLP 端点指向 Langfuse 的 OTLP 入口即可，**代码零改动** | 极低 |
| RAGAS（语义指标） | `evaluation/metrics.py` 是纯函数、`runner.py` 只依赖「指标可计算」这一形状 —— 新增一个 RAGAS 版指标实现并在 runner 中替换即可，golden set 与报告结构不变 | 中（需 LLM Key） |

---

## 8. 实测结果（本机，2026-10-05）

```
$ py -3 -m dw_infrastructure.evaluation
{
  "dataset": "aftersales-golden-v1",
  "k": 3,
  "ingested_documents": 8,
  "metrics": {"hit_at_k": 1.0, "recall_at_k": 1.0, "precision_at_k": 0.3333, "mrr": 1.0, "cases": 8}
}
```

8 个用例全部首位命中（`precision@3 ≈ 1/3`，因为每案只有 1 个相关项，属正常值）。
回归阈值定为 `hit / recall / MRR ≥ 0.875`、`precision ≥ 0.3` —— 留出「最多 1 例退化」的余量。

> 说明：这是**确定性冒烟级质量闸门**（FakeEmbedder + 纯函数指标），用于防止检索链路被改坏；
> 它**不是**语义质量基准，语义质量评估需接 RAGAS（见 §7）。

---

## 9. 非目标（明确未做）

* Langfuse / RAGAS 的真实接入（仅留接缝）。
* LLM-as-judge 类主观评估。
* 日志采集/存储栈（ELK / Loki）与 Grafana 面板、告警规则与 on-call 流程。
* Prometheus `/metrics`（RED 指标）—— 本轮范围外，可后续增补。
* 采样策略调优、Tail-based sampling、跨进程 trace 上下文注入（`traceparent` 透传）。
