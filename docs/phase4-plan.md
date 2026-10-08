# Phase 4 实施计划（草案，待确认）

> 本文是 **计划草案**，尚未开始实现。需用户确认范围后方可动工。
> 依据：`docs/architecture.md` 相位表（Phase 4 = Specialist Agent + RAG）、
> 现有骨架代码注释中的 § 引用、以及 `supervisor/planner.py` 的 `MISSING_CAPABILITY_HINT`。
> **仓库内没有独立的 Phase 4 需求文档**，本计划由上述真实代码与架构说明推导而来。

---

## 0. 范围判断与一处相位冲突

- `architecture.md` 把 Phase 4 映射到 **Specialist Agent（专业领域判断）+ RAG（外部知识证据）**，
  且 `database.md` 明确 pgvector "供 Phase 4 的 RAG 复用"，`README.md` 写 RAG 为 "⏳ Phase 4+"。
- 但 `docs/agent-runtime.md` §5 把 Design/Quote/Construction/AfterSales 四个 Specialist 落地说成
  "随 Phase 5-7 落地"，与 architecture.md 的 "Phase 4" **不一致**。
- **处理方式（不越界）**：以 `architecture.md` 相位表为准，但 Phase 4 **只落地一个试点 Specialist
  —— AfterSales**，其余三个领域 Agent（Quote / Design / Construction）仍按计划留给 Phase 5-7。
  这样既兑现 Phase 4，又不抢别人的 Phase，也与仓库名为"装修售后 agent"的业务重心吻合。

---

## 1. 两个工作流（彼此独立，可各自先交付）

| 工作流 | 内容 | 是否依赖另一流 |
|--------|------|----------------|
| **A. RAG 证据底座** | 数据层 + 检索层，不绑任何业务 | 否（可独立落地与测试） |
| **B. AfterSales Specialist 试点** | 注册 AfterSales Agent + `aftersales_diagnosis` 技能 + 落地 `root_cause` / `case_match`，并用上 RAG | 依赖 A 的检索能力 |

> 因 B 依赖 A，建议顺序：先做 A（纯底座 + 测试），再做 B。但 A 可先于 B 单独验收。

---

## 2. 工作流 A — RAG 证据底座

### 2.1 落点（依 `architecture.md` §8：RAG 流水线 → `packages/infrastructure/rag` 增量）

新建 `packages/infrastructure/src/dw_infrastructure/rag/`：

- `embeddings.py`
  - `Embedder` 协议（`embed(texts: list[str]) -> list[list[float]]`）。
  - `FakeEmbedder`：**确定性、可复现、CI/测试友好、零外部依赖**，固定维度（如 256）。
    用稳定哈希 + 归一化，保证同输入同向量，便于确定性集成测试。
  - `OpenAIEmbedder`：真实嵌入器，gated by `Settings`（维度 1536），仅生产启用。
  - 维度由 `Settings` 配置，避免硬编码分块维度与索引维度不一致。
- 表（新增）
  - `documents`（`id`, `title`, `source`, `metadata JSONB`, `created_at`）
  - `document_chunks`（`id`, `document_id`, `seq`, `content`, `embedding vector(<dim>)`,
    `source`, `metadata JSONB`）
  - 需 `CREATE EXTENSION IF NOT EXISTS vector;`（pgvector 已内置在镜像）。
- `store.py`：`DocumentStore`
  - `upsert_document(...)` / `upsert_chunks(...)`（批量、幂等）。
  - 向量检索：`ORDER BY embedding <=> :query LIMIT k`（余弦距离，pgvector）。
  - 词法检索（BM25）：在 `content` 上建 `tsvector` + GIN 索引，用 `ts_rank`/`plainto_tsquery`
    做关键词匹配，提供 `bm25_search(query, k)`。
- `retrieval.py`：混合检索
  - `fuse_scores(vector_scores, bm25_scores)`：**Reciprocal Rank Fusion（RRF）纯函数**，可单测。
  - `Reranker` 接口 + `IdentityReranker`（占位，预留 cross-encoder 接缝）。
  - `retrieve(query, k)` → `RetrievalResult`（含 `chunks` + `score` + `provenance`
    [chunk_id, source, rank]）。
- 契约：在 `packages/schemas/src/dw_schemas/rag.py` 定义 `Chunk` / `Document` / `RetrievalResult`。

### 2.2 Alembic 迁移

- 新迁移（如 `phase4_rag`）：`CREATE EXTENSION vector`；建 `documents` / `document_chunks`；
  GIN 索引（BM25）+ 向量索引（`hnsw` 或 `ivfflat`，依 pgvector 0.8 默认支持）。
- 保持 `alembic/env.py` 只从 `Settings` 读连接串（不重复配置 `alembic.ini`）。
- 更新 `docs/database.md`：新增 Phase 4 表清单 + 迁移历史行。

### 2.3 RAG 接入点（不绑业务）

- 通过一个可测试的服务函数 / 内部接口暴露（如 `RagService.search` 或内部 `POST /api/v1/rag/search`），
  供 B 与未来 Specialist 复用。**本阶段不接任何 Agent**，纯底座。

### 2.4 工作流 A 的 Definition of Done

- `./scripts/dev.ps1 migrate` 应用成功（含 pgvector 扩展）。
- 单测：`FakeEmbedder` 确定性；`fuse_scores` RRF 排序正确；BM25 `ts_rank` 命中关键词。
- 集成测试：写入若干 chunk → 向量 top-k 返回最邻近 → 混合检索返回带 provenance 的结果。
- 不接 Agent，纯底座验收。

---

## 3. 工作流 B — AfterSales Specialist 试点

### 3.1 复用现有编排（不新造编排）

现有 `AgentRegistry` / `SkillRegistry` / `ToolExecutor` / `Supervisor`（intent→planner→runner）
已具备完整路由执行能力。AfterSales 只是"一个新 `AgentType` + 它的 `Skill`/`Tool` + 一个 `SkillRunner`"，
**不需要新增编排代码**。

### 3.2 注册（seed / fixtures）

- Agent：`aftersales_agent`（`agent_type=aftersales`）。
- Skill：`aftersales_diagnosis`（风险等级见 §7 待确认问题 2）。
- Tools：
  - `case_search`：检索售后知识库 / 案例（经 RAG）。
  - `root_cause`：基于 RAG 证据 + 关键词规则，产出根因假设与处置建议（带置信度）。
  - `case_match`：用 embedding 匹配最相似的历史案例（带相似度）。
- 在 seed 脚本 / fixtures 注册三件套，并通过 `RuntimeRegistries.validate_task` 一致性校验。

### 3.3 SkillRunner

`run_aftersales_diagnosis(ctx, payload)`：

1. 调 `case_search` → 经 RAG 检索相关售后知识 / 案例（provenance 带 chunk_id + source）。
2. 调 `root_cause` → 基于检索证据 + 关键词规则产出根因假设与建议（带置信度）。
3. 调 `case_match` → 用 embedding 取 top-k 相似历史案例（带相似度）。
4. 产出 Artifact `aftersales_diagnosis`，payload 含
   `hypothesis` / `suggestions` / `evidence`（引用 chunk_id、source、score）/ `similar_cases`。

接入 `SKILL_RUNNERS["aftersales_diagnosis"]`。

### 3.4 意图 / 规划接线

- `planner.py`：
  - `INTENT_CAPABILITY[IntentType.AFTERSALES_DIAGNOSIS] = ("aftersales_agent", "aftersales_diagnosis")`
  - 从 `MISSING_CAPABILITY_HINT` 删除 `AFTERSALES_DIAGNOSIS` 条目（不再返回 501）。
- `intent.py`：**不改规则**（规则路由已能命中 AfterSales 关键词：渗水/漏水/维修/售后/工单/整改/开裂/返工）。
  模型化按注释留到 "Phase 4 之后"。

### 3.5 工作流 B 的 Definition of Done

- seed 后 `GET /skills` 列出 `aftersales_diagnosis` 为**已实现**（不再 501）。
- 发送含"渗水 / 维修"等词的 objective → `POST /runs` → Supervisor 路由到 `aftersales_agent`
  → `PlanRunner` 执行 → 任务 `succeeded` 且产出 `aftersales_diagnosis` Artifact（含 RAG 证据引用）。
- 集成测试覆盖端到端（用 `FakeEmbedder` + 预置知识 chunk，确定性）。
- `MISSING_CAPABILITY_HINT` 不再把 AfterSales 标为缺失。

---

## 4. 明确的非目标（避免过度设计 / 越界）

- **意图模型化（规则→ML）**：`intent.py` 注释明确 "Phase 4 之后"，本阶段只接线，不动路由实现。
- **Mem0 长期记忆**：Phase 5+。
- **Kafka / Redis 主动场景**：Phase 7。
- **真实 cross-encoder Reranker**：本阶段只留接口 + `IdentityReranker` 占位。
- **Quote / Design / Construction 三个 Specialist**：留给 Phase 5-7（与 `agent-runtime.md` §5 一致）。
- **MCP 传输层（stdio/HTTP）**：未到跨进程调用阶段，不动（见 `agent-runtime.md` §6）。

---

## 5. 测试与质量门槛（沿用 Phase 3 Gate 风格）

- **单元**：embeddings 确定性、`fuse_scores`、BM25、`retrieval` 排序、`skill_runner` 纯逻辑。
- **集成**（pytest + 真实 PG/pgvector，复用现有 `tests/integration/conftest.py` 与
  docker postgres `:55432`）：RAG 写入 + 检索、AfterSales 端到端。
- 全量 `pytest tests/unit tests/integration` 绿；`read_lints` 无新增 error；
  `./scripts/dev.ps1 migrate` 干净。
- 文档更新：`database.md`（Phase 4 表）、`agent-runtime.md`（RAG + AfterSales 章节）、
  `architecture.md`（Phase 4 项 ⏳ → ✅/🔧）。

---

## 6. 交付物

- `Phase 4 Gate 报告`（§30 风格：已落地能力、验证结果、残留风险、是否进入 Phase 5）。

---

## 7. 待你确认的三个问题

1. **范围**：A+B 都做（推荐，形成 RAG↔Specialist 垂直切片），还是先只做 A（RAG 底座）或只做 B（AfterSales，此时 RAG 先用最简向量检索顶替）？
2. **AfterSales 风险等级**：用 **L1**（端到端可直接跑，不触发审批门控，便于验证）还是按 §15 用 **L2**（需审批，顺带验证"审批→检查点恢复"链路）？
3. **嵌入器**：先用 **`FakeEmbedder`**（CI/测试零外部依赖，确定性）还是直接接 **OpenAI 兼容嵌入**（需 API Key，真实语义检索）？

> 确认后我会按 Phase Gate 流程实现 + 跑测试 + 出 Gate 报告；未确认前不写业务代码。
