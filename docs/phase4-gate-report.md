# Phase 4 Gate 报告（§30）

> 阶段：Phase 4 —— Specialist Agent（专业领域判断）+ RAG（外部知识证据）
> 日期：2026-10-05
> 结论：**PASS**，可进入 Phase 5（领域 Specialist 落地：Design / Quote / Construction）

---

## 0. 范围与边界（与计划一致）

- 按 `docs/phase4-plan.md` 落地 **A. RAG 证据底座** + **B. AfterSales Specialist 试点**，只落地一个试点 Specialist，
  不抢 Phase 5-7 的三个领域 Agent（Design / Quote / Construction）。
- 已调和 `architecture.md` 与 `agent-runtime.md §5` 的相位冲突：以架构相位表为准，AfterSales 在 Phase 4 试点。
- **非目标（明确未做）**：意图路由模型化（规则→ML）、Mem0 长期记忆、Kafka/Redis 主动场景、
  真实 cross-encoder Reranker（仅留接口 + `IdentityReranker` 占位）、MCP 传输层。

---

## 1. 已落地能力

### A. RAG 证据底座（`packages/infrastructure/rag/`）
- `embeddings.py`：`Embedder` 协议 + `FakeEmbedder`（确定性、零外部依赖，CI/测试）
  + `OpenAIEmbedder`（真实嵌入器可插拔接缝，gated by `Settings`）。
- `models.py`：`rag_documents` / `rag_document_chunks` ORM（子类 `dw_domain.models.Base`，纳入 Alembic metadata）。
- `store.py`：`DocumentStore` 文档写入（切块 + 嵌入）、向量检索（pgvector `<=>` 余弦）、BM25（`tsvector`/`ts_rank`）、`similar_cases`（按 `metadata.kind='case'` 过滤）。
- `retrieval.py`：`fuse_scores`（RRF 纯函数）、`Reranker` 接口 + `IdentityReranker`、`retrieve`（向量 + BM25 → RRF → 重排 → 带 provenance 的 `RetrievalResult`）。
- Alembic 迁移 `5a1b2c3d4e5f`：`CREATE EXTENSION vector` + 两张表 + HNSW 向量索引 + GIN 索引（维度来自 `Settings.rag_embedding_dim`）。
- **稳健性关键决策**：不依赖 asyncpg 二进制向量 codec —— 写入走 pgvector.sqlalchemy 文本绑定，读取走
  `embedding <=> cast(:q as vector)` + `embedding::text`，仅依赖服务端 pgvector 扩展（已在本机 pgvector/pgvector:pg16 验证）。

### B. AfterSales Specialist 试点
- 注册 `aftersales_agent`（agent_type=aftersales）、`aftersales_diagnosis`（L1）、三个 RAG 工具
  `case_search` / `root_cause` / `case_match`（均 L0，经 `rag_tools.py` 并入 `BUILTIN_TOOLS`）。
- `skills.run_aftersales_diagnosis` 编排三个 RAG 工具，产出带**证据引用**的 `aftersales_diagnosis` Artifact（§34）。
- `planner.py`：`AFTERSALES_DIAGNOSIS` 接入 `INTENT_CAPABILITY`，并从 `MISSING_CAPABILITY_HINT` 移除（不再 501）；
  新增 `_aftersales_plan`（单步 direct，输入带 issue + project_id）。
- 意图规则路由（`intent.py`）无需改动，已能命中渗水/漏水/维修/售后/工单等关键词。

---

## 2. 验证结果

### 全量测试（真实 PostgreSQL + pgvector，docker `dw-postgres` 健康）
```
pytest tests/unit tests/integration → 229 passed, 0 failed, 0 error
```
- 单元（无 DB）：`test_rag.py`（FakeEmbedder 确定性/相似度、RRF 融合、retrieve 组合与重排）、
  `test_aftersales_skill.py`（技能编排：按 issue 调对工具、收敛证据/根因/相似案例、缺 issue 报错）。
- 集成（有 DB）：`test_rag_store.py`（写入 + 向量检索 + BM25 + similar_cases + 混合检索）、
  `test_aftersales.py`（端到端：提交售后意图 → 路由 → 计划 → 技能执行 → 任务 succeeded + 带引用 Artifact；
  `GET /skills` 列出 aftersales_diagnosis 为已实现）。
- 回归：原 `test_unsupported_intent_is_501` 改为仍属 Phase 5 的 `quote_estimate`；新增
  `test_aftersales_diagnosis_requires_no_longer_501` 保护「aftersales 不再 501」。

### 运行期校验
- `alembic upgrade head` 应用成功（修正为线性链：…→ `4f1a2b3c5d6e` → `5a1b2c3d4e5f`）。
- 已确认 `rag_document_chunks.embedding` 为 `vector` 类型、`vector` 扩展存在。

### Lint
- 全部改动文件 `read_lints` 零 error / warning。

---

## 3. 残留风险 / 待办（不阻塞 Phase 5）

1. **嵌入维度**：默认 256（`FakeEmbedder`）。启用 `OpenAIEmbedder`（1536 维）须同步改
   `Settings.rag_embedding_dim` 并重新生成迁移 —— 已写入代码注释与 `docs/database.md`。
2. **Reranker 为占位**：`IdentityReranker` 仅原样返回；真实 cross-encoder 重排是后续接缝，未做。
3. **RAG 内容来源**：当前知识库由测试/业务侧写入，尚无「知识入库流水线」（抓取/切分/质检），属 Phase 5+ 数据工程。
4. **BM25 对中文**：`to_tsvector('simple')` 对 CJK 不做分词，语义主要由向量检索承担；中文词法检索需后续引入
   `zhparser` 或 n-gram 配置。
5. **其余三个 Specialist**：Design / Quote / Construction 仍按 `agent-runtime.md` 规划留给 Phase 5-7。

---

## 4. 是否进入 Phase 5

**建议：可进入 Phase 5。** Phase 4 定义的底座（RAG + 一个试点 Specialist 的端到端闭环）已通过全量测试与运行期校验。
Phase 5 建议落地 **Quote（报价估算）Specialist**（业务价值高、且 `agent-runtime.md §5` 已规划），复用本阶段 RAG 与编排骨架。
