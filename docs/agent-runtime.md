# Agent Runtime 说明（Phase 2 + Phase 3）

> 对应需求文档 §4 / §5 / §6 / §7 / §8 / §9 / §11 / §12 / §15 / §32 / §34。
> Phase 3 在 Phase 2 的注册中心 / 工具治理 / Run-Task 生命周期之上，补齐了
> **Supervisor 编排**：意图路由、限额规划、三种 DAG 执行模式、节点级检查点恢复、复核。

## 1. 组件与职责

| 组件 | 落点 | 负责回答 |
|------|------|----------|
| AgentRegistry | `dw_agent_runtime/registry.py` | 有哪些 Agent、各自支持哪些 Skill |
| SkillRegistry | 同上 | Skill 属于哪种 Agent、允许调用哪些 Tool |
| ToolRegistry | 同上 | Tool 的超时/重试/降级/幂等/审计策略 |
| ToolDefinition | `dw_agent_runtime/tools.py` | 工具能力本体（入参模型 + handler） |
| ToolExecutor | `dw_agent_runtime/executor.py` | 单次工具调用的治理链 |
| SkillRunner | `dw_agent_runtime/skills.py` | 技能决定调哪些工具、产出什么 Artifact |
| RunService | `dw_agent_runtime/runs.py` | Run/Task 生命周期（Direct 模式） |

## 2. Run / Task / Artifact 模型

```
AgentRun (objective, status, mode)
   ├── AgentTask (agent_id, skill_id, allowed_tools, risk_level, attempt)
   │        └── ToolCall × N (tool_id, status, attempt, duration_ms, idempotency_key)
   ├── Artifact (artifact_type, producer, payload, version)   ← §34 只传 id
   ├── Approval (status, reason, decided_by)                  ← §15 高风险门控
   └── AuditLog (action, resource_type, resource_id, details) ← §12 审计
```

外键删除策略：`agent_tasks` / `artifacts` / `tool_calls` / `approvals` 对 Run 用 CASCADE；
`agent_runs.project_id` / `requester_id` 对业务表用 RESTRICT（业务事实不被 Agent 日志连坐删除）。

## 3. 治理链（§12）

```
1 permission    校验 tool.required_scopes ⊆ 调用方权限（admin 免检）      → 403/TOOL_PERMISSION_DENIED
2 schema        Pydantic 模型校验入参                                    → 400/TOOL_VALIDATION_ERROR
3 idempotency   有 key 且存在成功记录 → 直接回放；同 key 并发 → 冲突       → 409/TOOL_CONFLICT
4 concurrency   按 tool_id 维度信号量限流（默认 4）
5 timeout       asyncio.wait_for(tool.timeout_ms)                      → 504/TOOL_TIMEOUT
6 retry         仅对超时/不可用重试，权限与入参错误不重试
7 fallback      重试耗尽后调用 fallback_tool_id（降级本身不再触发降级）
8 audit         落 tool_calls + audit_logs（拒绝也留痕）
```

### 为什么只有超时/不可用才重试

权限不足、入参非法属于**确定性失败**，重试一万次结果一样，只会放大下游压力并拖长 Run 的耗时。

### 幂等的两种语义

* 相同 `idempotency_key` 的第二次调用：**回放**上次成功结果，不重复执行（也不重复计费/写库）；
* 相同 `idempotency_key` 的并发调用：第二个直接 `TOOL_CONFLICT`，避免同 키 双写。

## 4. 风险等级与审批（§15）

| 等级 | 行为 |
|------|------|
| L0 / L1 | 直接执行 |
| L2 / L3 | 建 `approvals` 待审单，Run 置 `awaiting_approval`，**审批前不产生任何 Artifact** |

审批接口：`POST /api/v1/approvals/{id}/approve` 与 `/reject`（需 `project:write`）。
当前审批完成的是「决策 + 留痕」；**从审批处恢复执行依赖 Checkpoint，属于 Phase 3**，
因此 approve 后 Run 仍停在 `awaiting_approval`，reject 则直接置 `failed`（终态）。

## 5. 已注册的能力（seed）

| 类型 | 标识 |
|------|------|
| Agent | `supervisor_agent`（supervisor）、`aftersales_agent`（aftersales，Phase 4 试点）、`quote_agent`（quote，Phase 5）、`design_agent`（design，Phase 6）、`construction_agent`（construction，Phase 7） |
| Skill | `project_snapshot`（L0，允许 project_query / artifact_query）、`aftersales_diagnosis`（L1，允许 case_search / root_cause / case_match）、`quote_estimate`（L0，允许 budget_estimate / package_compare / material_lookup）、`design_proposal`（L0，允许 layout_analysis / style_match）、`construction_review`（L0，允许 progress_analysis / quality_check） |
| Tool | `project_query` / `project_list` / `artifact_query`（均 L0）；`case_search` / `root_cause` / `case_match`（均 L0，RAG 驱动，Phase 4）；`budget_estimate` / `package_compare` / `material_lookup`（均 L0，业务表驱动，Phase 5）；`layout_analysis` / `style_match`（均 L0，业务表驱动，Phase 6）；`progress_analysis` / `quality_check`（均 L0，业务表驱动，Phase 7） |

> AfterSales（Phase 4 试点）、Quote（Phase 5）、Design（Phase 6）与 Construction（Phase 7）都是**垂直切片 Specialist**：它们复用现有 Supervisor 编排，
> 不需要新编排代码，只是「一个新 AgentType + 它的 Skill/Tool + 一个 SkillRunner」。
> AfterSales 接入 RAG 证据底座，Quote / Design / Construction 接入业务表驱动计算（RAG + 业务表两条数据源路线，验证同一骨架的通用性）。
> §5 的四个领域 Specialist 至此全部落地。

## 7. Phase 3：Supervisor 编排（§4 / §5 / §7 / §9 / §32）

| 组件 | 落点 | 职责 |
|------|------|------|
| Intent Router | `supervisor/intent.py` | 规则路由：自然语言 → 意图（纯函数、可单测、可解释） |
| Planner | `supervisor/planner.py` | 意图 + 可见项目 → 受 `PlannerLimits` 约束的 `Plan`（DAG） |
| DAG 校验 | `supervisor/dag.py` | 拓扑分层（Kahn）、环检测、max_steps/max_depth/max_parallel 限额 |
| PlanRunner | `supervisor/runner.py` | 三种模式：`direct` / `sequential` / `parallel_dag`；并发任务各自开会话 |
| Checkpoint | `models/agent_runtime.Checkpoint` | 节点级恢复：`(run_id, task_id, version)` 唯一，恢复时从最后完成节点续跑 |
| Reviewer | `supervisor/reviewer.py` | 纯函数复核 → PASS / RETRY / FALLBACK / HUMAN_REVIEW |
| RunService | `runs.py` | `execute_plan` / `preview_plan` / `resume` + `_finalize`（跑 Reviewer 定终态） |

### 执行模式

* `direct`：单任务，一条链。
* `sequential`：DAG 只有一条链，下游通过 `artifact_id` 复用上游结果（§34）。
* `parallel_dag`：同一拓扑层内互不依赖的任务并发执行，每个任务独立 `AsyncSession`、
  只操作自己那一行 `agent_tasks`；扇出前先提交，保证并发会话能看到 Run/Task 行。

### 失败与恢复（不吞、不假装成功）

* 可恢复错误（超时 / 下游不可用）在 `retry_limit` 内重试；
* 结构性失败（如技能没有执行体）**不重试**，直接判 `FALLBACK` 并附具体错误；
* 高风险技能 → 建审批单并停在 `awaiting_approval`，已完成节点写入 Checkpoint；
* 审批通过后 `POST /runs/{id}/resume` 从检查点恢复，未审批节点重新执行。

### 限额（§32，防无限展开）

`PlannerLimits(max_steps=8, max_depth=3, max_parallel=3, deadline_ms=30000, retry_limit=1)`，
由 `validate_plan` 在生成后立刻校验。

### 已注册的可编排能力（seed）

`supervisor_agent` + `project_snapshot` 支持 `project_overview` / `project_compare` 两类意图；
`aftersales_agent` + `aftersales_diagnosis` 支持 `aftersales_diagnosis`（Phase 4，端到端可跑）；
`quote_agent` + `quote_estimate` 支持 `quote_estimate`（Phase 5，端到端可跑，业务表驱动）；
`design_agent` + `design_proposal` 支持 `design_proposal`（Phase 6，端到端可跑，业务表驱动）；
`construction_agent` + `construction_review` 支持 `construction_review`（Phase 7，端到端可跑，业务表驱动）；
四个领域意图至此全部可编排；`MISSING_CAPABILITY_HINT` 清空（保留结构，供未来能力缺失时声明 Phase）。

## 8. Phase 4：RAG 证据底座（§8）

RAG 流水线落在 `packages/infrastructure/rag/`，与业务编排解耦：

| 组件 | 落点 | 职责 |
|------|------|------|
| `embeddings.py` | 同上 | `Embedder` 协议；`FakeEmbedder`（确定性、零依赖，CI/测试）+ `OpenAIEmbedder`（真实嵌入器接缝，gated by `Settings`） |
| `models.py` | 同上 | `rag_documents` / `rag_document_chunks` 两表 ORM（子类 `dw_domain.models.Base`） |
| `store.py` | 同上 | `DocumentStore`：文档写入（切块 + 嵌入）、向量检索（`<=>`,、BM25（tsvector/ts_rank） |
| `retrieval.py` | 同上 | `fuse_scores`（RRF 纯函数）、`Reranker` 接口 + `IdentityReranker` 占位、`retrieve`（混合检索） |

设计要点：**不依赖 asyncpg 的二进制向量 codec** —— 写入走 pgvector.sqlalchemy 的文本绑定，
读取走 `embedding <=> cast(:q as vector)` + `embedding::text`，只依赖服务端 pgvector 扩展。
`retrieve` 组合向量 + BM25 → RRF 融合 → `Reranker` 接缝 → 返回带 provenance 的 `RetrievalResult`。

AfterSales 的三个工具（`case_search` / `root_cause` / `case_match`）即基于 `DocumentStore` 检索，
由 `skills.run_aftersales_diagnosis` 编排成带证据引用的 Artifact（§34）。

## 6. MCP 传输层（已交付）

**Tool Runtime**：工具以 `ToolDefinition(handler, input_model)` 注册，对外契约（工具清单、入参/出参 JSON Schema、调用语义）与 MCP 对齐。

**stdio 传输层**（`apps/mcp-server`，包 `dw_mcp_server`）：把注册中心里「已启用」的工具经 MCP 协议暴露给跨进程调用方，
自实现 JSON-RPC 2.0 子集（`initialize` / `ping` / `tools/list` / `tools/call`），**零第三方依赖**。

* 工具调用经 `ToolExecutor`（scope → schema → 幂等 → 超时 → 重试 → 审计），与 HTTP 入口**权限口径一致**；
* MCP 无 Run 概念：为每个身份懒创建一个「MCP 会话 Run」承载 `tool_calls` / 审计，避免无主记录；
* 鉴权取 `params._meta.authorization`（Bearer）或 `DW_MCP_TOKEN`；`tools/list` 只回元数据、无需鉴权。

详见 [`docs/mcp-transport.md`](./mcp-transport.md)。
