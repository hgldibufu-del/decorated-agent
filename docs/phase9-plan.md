# Phase 9 实施计划（可观测与评估）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：Phase 0-7 + 前端工作台 + CRUD + MCP 传输层均已交付；三个平台课题的第 2 个。

---

## 1. 现状（已具备的观测能力）

| 能力 | 位置 | 说明 |
|------|------|------|
| 结构化日志 | `dw_infrastructure/logging_setup.py` | 单行 JSON；`request_id` / **`trace_id` 两个 ContextVar 已存在并由 JsonFormatter 输出**；敏感字段递归脱敏 |
| 请求上下文 | `dw_api/middleware.py` | 纯 ASGI 中间件：绑定 request_id、`duration_ms`、回写 `X-Request-ID` / `x-process-time-ms` |
| 审计事实 | `audit_logs` / `tool_calls` / `agent_runs` / `agent_tasks` / `checkpoints` | 工具调用的 status / attempt / duration_ms / error 已落库 |
| 健康探针 | `GET /live` `/ready` `/health` | 依赖分级聚合（可单测纯函数） |

**关键接缝**：`trace_id_var` 已预留且日志已输出 `trace_id` —— 只差把 OpenTelemetry 的真实 trace_id 绑进去，日志与 trace 即可互相关联。

**缺口**：没有分布式链路追踪（无 span / 无父子关系 / 无跨进程传播）；没有评估基线（无 golden set、无检索指标）。

---

## 2. 依赖现实（决定 Phase 9 能做到哪一层）

| 组件 | 现状 | 结论 |
|------|------|------|
| `opentelemetry-api` / `-sdk` / `-exporter-otlp` | 未安装，**可安装**（已验证 1.45.0 可获取） | ✅ 真实接入 |
| `langfuse` | 未安装；需外部服务（SaaS / 自建）+ Key | ❌ 不做硬依赖，留**接缝** |
| `ragas` | 未安装；评估需 LLM + embeddings，**非确定性** | ❌ 不做硬依赖，留**接缝** |

架构约束（`architecture.md` §2）：**`packages/infrastructure` 是唯一允许持有外部 SDK 的共享包** → OTel 依赖与封装放这里。

---

## 3. 交付范围（推荐）

### A. OpenTelemetry 链路追踪（真实接入）
* 新增 `packages/infrastructure/src/dw_infrastructure/observability/`：
  * `tracing.py`：`configure_tracing(settings)` 装配 TracerProvider —— 配了 `OTEL_EXPORTER_OTLP_ENDPOINT` 就用 OTLP 导出，否则用**只装配、不导出**（零副作用，测试友好）；`get_tracer(name)`；`bind_trace_context()` 把当前 span 的 trace_id 写入既有 `trace_id_var`（**日志 ↔ trace 打通**）；属性一律经 `redact` 脱敏。
* 探针落点（按价值排序）：
  1. **Tool 调用**（`ToolExecutor`）：`tool_id` / `status` / `attempt` / `duration_ms` / `risk_level` —— 治理链已有全部数据；
  2. **Run / Task**（`RunService`）：`run_id` / `intent` / `mode` / `status` / `review_decision`；
  3. **HTTP 请求**：新增纯 ASGI 追踪中间件（保持纯 ASGI，不破坏未来 SSE）；
  4. **RAG 检索**（`retrieve`）：`strategy` / 命中数 / 阶段耗时。
* 配置项进 `Settings`（`OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` / `OTEL_TRACES_SAMPLER_RATIO`），生产默认关闭导出、可按需开启。

### B. 评估（确定性，可回归）
* `packages/infrastructure/src/dw_infrastructure/evaluation/`：
  * `golden.py`：golden set 的加载与形状（`query` → 期望命中的 `document_id` / 关键词）；
  * `metrics.py`：**纯函数**指标 —— `hit@k` / `recall@k` / `MRR` / `precision@k`；
  * `runner.py`：跑 golden set → 汇总报告（分策略：vector / bm25 / hybrid）。
* 数据：`evaluation/datasets/aftersales_golden.yaml`（复用 Phase 4 的售后知识语料，不新增业务语料）。
* 落地形式：既可由 CLI 运行（`py -3 -m dw_infrastructure.evaluation`），也可作为 **pytest 回归用例**守住检索质量下限（指标不得低于阈值）。
* **RAGAS 接缝**：`Metric` 为 Protocol，RAGAS 版本只需实现同一协议即可替换，无需改动 runner / 数据集。

### C. （可选）Prometheus `/metrics`
* `GET /api/v1/metrics` 暴露 RED 指标（请求数 / 错误数 / 时延直方图）；`prometheus_client` 本机已存在但**未在依赖中声明**，需一并声明。

---

## 4. Definition of Done

- [ ] `configure_tracing` 可装配；未配置端点时**零副作用**（不影响现有测试与启动）。
- [ ] Tool / Run / HTTP / RAG 四类 span 落地；span 属性经脱敏。
- [ ] **日志中的 `trace_id` 与 span 的 trace_id 一致**（打通验证有测试）。
- [ ] 评估 harness 可跑出确定性报告（hit@k / recall@k / MRR），并有 pytest 阈值回归。
- [ ] 全量测试全绿（新增用例 ≥ 15）；`read_lints` 零错误。
- [ ] 文档更新（`architecture.md` §9 状态、`docs/observability.md`、`README`）+ Phase 9 Gate 报告。

---

## 5. 非目标（明确未做）

- Langfuse / RAGAS 的真实接入（留协议接缝：需外部服务与 LLM，无法离线确定性验证）。
- LLM-as-judge 类主观评估。
- 日志采集/存储栈（ELK / Loki）与 Grafana 面板。
- 告警规则与 on-call 流程。
- 采样策略调优、Tail-based sampling。
