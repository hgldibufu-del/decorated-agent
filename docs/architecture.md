# 架构说明（Architecture）

> 对应需求文档 §3、§9、§23、§38 的职责边界要求。
> 本文描述**当前仓库中真实存在的代码**，不描述尚未实现的模块。

---

## 1. 职责边界总表

任何新增代码都必须能回答「它属于哪一层、为什么放这里」；回答不了就不应该加入。

| 边界 | 负责回答的问题 | Phase 0 落点 |
|------|----------------|--------------|
| `apps/api` | HTTP 协议转换、横切中间件、错误出口 | ✅ 已实现 |
| `packages/schemas` | 跨进程数据形状（契约） | ✅ 已实现 |
| `packages/domain` | 业务规则、持久化模型、应用服务 | ✅ Phase 1 已实现 |
| `packages/infrastructure` | 外部世界的连接与观测适配 | ✅ 已实现 |
| Supervisor | 谁做、为什么做、先做什么后做什么 | ⏳ Phase 3 |
| LangGraph | 怎么编排、恢复、重试 | ⏳ Phase 3 |
| Specialist Agent | 专业领域判断 | ✅ Phase 4（AfterSales）+ Phase 5（Quote）+ Phase 6（Design）+ Phase 7（Construction）全部落地 |
| Skill | 业务能力封装 | ⏳ Phase 2 |
| MCP | 标准化 Tool 调用 | ✅ 已实现（`apps/mcp-server`，stdio JSON-RPC 子集） |
| PostgreSQL | 业务事实 | ✅ 已接线（Phase 1 落业务表） |
| RAG | 外部知识证据 | ✅ Phase 4（pgvector + BM25 + Reranker 接缝；AfterSales 试点已接入） |
| Mem0 | 长期偏好 | ✅ Phase 10（自建确定性记忆层；mem0ai 留 `MemoryStore` / `MemoryExtractor` 协议接缝） |
| Kafka | 业务事件（发生了什么） | ✅ 已接线（Phase 7 做主动式） |
| Redis | 短期运行状态 | ✅ 已接线 |
| Reviewer | 质量门控 | ⏳ Phase 3 |
| OpenTelemetry | 链路追踪（请求 / Run / Tool / RAG） | ✅ Phase 9（未配置端点时 no-op，零副作用） |
| Langfuse / RAGAS | 语义评估 | ⏳ 留协议接缝（需外部服务 / LLM，非确定性，暂不硬依赖） |

---

## 2. 分层依赖方向

```
apps/api ──► packages/domain ──► packages/infrastructure ──► packages/schemas
                                          │
                                          └──► PostgreSQL / Redis / Kafka
```

规则：

* **`packages/schemas` 不依赖任何东西**（除 Pydantic）。这里只有形状，没有 IO。
* **`packages/infrastructure` 是唯一允许持有外部 SDK 的共享包**，但不包含业务规则。
* **`apps/api` 不得直接写 SQL、不得直接调 LLM**；它是 Controller，只做协议与横切事宜。
* 下层永远不能反向引用上层。

---

## 3. 请求生命周期

```
HTTP 请求
  │
  ├─ RequestContextMiddleware   绑定 request_id → ContextVar，回写响应头，记录访问日志
  ├─ SecurityHeadersMiddleware  nosniff / DENY / Referrer-Policy / Permissions-Policy
  ├─ CORSMiddleware             白名单跨域（最后注册 → 最外层，预检请求在此短路）
  │
  ├─ Router ──► Application Service（后续 Phase）──► Domain ──► Repository
  │
  └─ 异常处理器 ──► 统一 ErrorEnvelope {code, message, request_id, retryable, category, details}
```

### 3.1 为什么中间件是纯 ASGI 而不是 `BaseHTTPMiddleware`

Phase 3 起需要 SSE（`GET /runs/{run_id}/stream`）。`BaseHTTPMiddleware` 会把响应
完整缓冲后才转发，从而破坏流式。因此 `RequestContextMiddleware` 与
`SecurityHeadersMiddleware` 都是手写 ASGI。

### 3.2 Starlette 中间件注册顺序

Starlette 中**后注册的中间件处于更外层**（先收到请求）。因此注册顺序是：

```python
app.add_middleware(RequestContextMiddleware)  # 最内层
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, ...)  # 最外层：预检在此短路
```

---

## 4. 统一错误处理

`packages/schemas/src/dw_schemas/envelope.py` 定义错误码注册表 `ERROR_SPECS`：

```python
ErrorCode.TOOL_TIMEOUT -> ErrorSpec(category=TOOL, http_status=504, retryable=True, ...)
```

设计要点：

* `code` / `category` / `retryable` / `http_status` **全部由注册表推导**，
  不允许在具体端点里各写一套（避免同码不同行为）。
* 新增 `ErrorCode` 必须同时登记 `ErrorSpec`，单测 `test_every_error_code_has_a_spec` 会兜住。
* Starlette 原生 404/405 也映射到业务错误码，保证出口只有一种结构。
* 未捕获异常归一化为 `INTERNAL_ERROR`，但 `logger.exception` 记录完整堆栈 ——
  既不向客户端泄漏内部细节，也不把错误吞掉。

错误分类覆盖需求 §25 要求的全部类别：
`user_error` / `validation_error` / `permission_error` / `tool_error` /
`model_error` / `database_error` / `infrastructure_error` / `internal_error`。

---

## 5. 健康检查模型

`HealthReport` = 系统状态 + 组件列表。聚合规则是**可单测的纯函数**：

1. 任一 `critical` 组件 unhealthy → `UNHEALTHY`（HTTP 503）
2. 任一组件 unhealthy（非 critical）或 degraded → `DEGRADED`（HTTP 200）
3. 其余 → `HEALTHY`（HTTP 200）

依赖分级：

| 组件 | critical | 理由 |
|------|----------|------|
| postgres | ✅ | 业务事实源，不可用则服务无法正确工作 |
| redis | ❌ | 短期状态/缓存，缺失应降级而非摘除实例 |
| kafka | ❌ | 业务事件总线，短时不可用可恢复后重放 |

探针失败**不会**被静默：会记录 `error_type` 与 `error` 日志，并把
`f"{type}: {message}"` 放进 `detail` 返回给运维。

---

## 6. 上下文与日志

* 单行 JSON 日志，字段含 `ts / level / logger / service / msg / request_id / trace_id`。
* `request_id` 通过 `ContextVar` 传递，天然支持 async task 隔离；若请求头未带则生成。
* `trace_id` 同样走 `ContextVar`：Phase 9 起由 span 生命周期绑定
  （`observability.start_span`），因此**一条日志可直接对应一条 trace**；
  未启用追踪时不写该字段，格式与接入前一致。
* **敏感字段脱敏**：任何键名命中 `api[-_]?key|secret|password|token|authorization|
  credential|private[-_]?key` 的结构化 extra 字段，出口一律替换为 `***REDACTED***`，
  并对嵌套结构递归生效（需求 §17）。span 属性走同一套脱敏后才写入 trace。

---

## 7. 配置与安全

`Settings`（pydantic-settings）是唯一配置入口，所有 app 共用。
生产环境（`APP_ENV=production`）启动即 fail-fast：

* `SECRET_KEY` 长度 ≥ 32 且非开发默认值
* `CORS_ORIGINS` 不得包含 `*`
* `APP_DEBUG` 必须为 `false`

未实现的部分（避免误解为已完成）：JWT / RBAC / Project ACL 属于 Phase 1，
健康检查端点当前是公开的。

---

## 8. 后续 Phase 的落位约定

| 模块 | 目标目录 |
|------|----------|
| MCP Tool Runtime | `apps/mcp-server` |
| AgentRegistry / SkillRegistry / ToolRegistry | `apps/agent-runtime` |
| Supervisor / Planner / DAG / Reviewer | `apps/agent-runtime` + LangGraph |
| MCP Tool Runtime | `apps/mcp-server` |
| Celery 任务 | `apps/worker` |
| 共享前端组件 | `packages/ui` |
| RAG 流水线 | `packages/infrastructure/rag`（增量） |
| 可观测（追踪门面 + 评估 harness） | `packages/infrastructure/observability` + `.../evaluation` |
| 记忆（存储 / 抽取协议 + 确定性实现） | `packages/infrastructure/memory` |
