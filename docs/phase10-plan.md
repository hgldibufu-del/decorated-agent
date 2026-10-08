# Phase 10 实施计划（记忆层 / Mem0）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：Phase 0-7 + 前端工作台 + CRUD + MCP 传输层 + Phase 9 可观测均已交付；三个平台课题的第 3 个（最后一个）。

---

## 1. 现状与缺口

| 已有 | 定位 | 是否够用 |
|------|------|----------|
| PostgreSQL 业务表 | 业务事实（项目 / 报价 / 设计 / 施工） | ✅ 事实 |
| RAG（pgvector + BM25） | 外部**知识**证据（文档、历史案例） | ✅ 知识 |
| Redis | 短期运行状态（`redis.py` 明写：**禁止当业务事实源**） | ❌ 不持久 |
| `audit_logs` / `agent_runs` | 发生过什么 | ❌ 非偏好 |

**缺口**：没有「跨 Run 复用的用户/项目长期偏好」。当前每次 `design_proposal` 都要调用方在
入参里重复给 `preference`；系统不记得「这位客户偏好新中式、对预算敏感、不接受延期」。

---

## 2. 依赖现实（决定能做到哪一层）

| 组件 | 现状 | 结论 |
|------|------|------|
| `mem0ai` | 可安装（2.2.1），但拖入 `openai` + `qdrant-client` + `posthog`（telemetry）+ `grpcio`；记忆抽取依赖 LLM | ❌ 不做硬依赖，留**协议接缝** |
| PostgreSQL | 已接线 | ✅ 记忆的单一事实源 |
| Redis | 已接线 | ⏸ 本轮**不做**缓存（项目明令 Redis 非事实源；缓存一致性是额外复杂度） |

判据与 Phase 9 一致：**确定性、可离线验证 → 真实接入；需外部服务或 LLM 判官 → 只留接缝。**

---

## 3. 交付范围（推荐）

### A. 数据层
* `dw_infrastructure/memory/models.py`：`UserMemory`（表 `user_memories`），子类化 `dw_domain.models.base.Base`
  —— 沿用 `rag/models.py` 的先例（infrastructure 里的 ORM 自带 Base 子类，由 `alembic/env.py` 注册）。
  * 列：`user_id`(FK→users, CASCADE)、`kind`、`key`、`value`(JSONB)、`confidence`、`source`、`hits`、`last_used_at`
  * 约束：`uq_user_memories_user_id_kind_key` → **按 (user, kind, key) 幂等 upsert**（同 Phase 6 name 唯一约束思路）
* Alembic 迁移 + `alembic/env.py` 注册。

### B. 记忆门面（infrastructure）
* `dw_schemas/memory.py`：`MemoryKind`（preference / constraint / fact）、`MemoryItem`、`MemoryProfile`
  —— 跨进程形状放 schemas（与其它契约一致）。
* `dw_infrastructure/memory/store.py`：
  * `MemoryStore` Protocol：`recall(user_id, kinds=None, limit)` / `remember(user_id, items, source)` / `forget(...)`
  * `PostgresMemoryStore`：幂等 upsert、命中计数（`hits` / `last_used_at`）
* `dw_infrastructure/memory/extractor.py`：
  * `MemoryExtractor` Protocol：`extract(text) -> list[MemoryCandidate]`
  * `RuleBasedExtractor`：**确定性**词典/正则抽取（风格偏好、预算敏感、工期要求、材料偏好…），可单测
  * **mem0ai 接缝**：将来实现同一 Protocol 即可替换，store / 编排 / 测试无需改动

### C. 编排接入（apps/agent-runtime）
* `RunService`：
  * **执行前**：加载 `MemoryProfile(user_id)` → 注入技能 payload 的 `memory` 键
    （Direct 模式注入 `input_payload`；Plan 模式注入每个 `step.input`）—— 四个 Specialist 自动复用；
  * **执行后**：用 `RuleBasedExtractor` 从 objective 抽取候选 → 幂等 upsert（`source="run:<id>"`）。
* 两个受治理工具（走完整治理链：scope → schema → 幂等 → 超时 → 重试 → 审计，并落在 timeline / trace 上）：
  * `memory_recall`（L0，`memory:read`）
  * `memory_remember`（L0，`memory:write`）
  * 挂载：`project_snapshot` 的 `allowed_tools` 增加 `memory_recall`
    —— 契合 §35「Supervisor 第一步加载项目上下文」。
* 权限：新增 `memory:read` / `memory:write`，授予 `PROJECT_MANAGER` 与四个 Specialist 角色。

### D. 落点验证（让记忆真的被消费，而不是「建了没人用」）
* `design_proposal`：payload 未给 `preference` 时，**回落到记忆画像里的风格偏好**
  → 可观察效果：同一句「出一套设计方案」，偏好新中式的用户与偏好北欧的用户得到不同首位风格。

### E. 测试
* 单测：`RuleBasedExtractor` 抽取与去重、`MemoryProfile` 渲染、`memory_recall` 工具的 schema 校验。
* 集成：
  1. `memory_remember` → `memory_recall` 幂等往返；
  2. 记忆影响 `design_proposal` 输出（偏好新中式 → 首位推荐新中式）；
  3. 缺 `memory:read` scope → 403；
  4. Run 完成后自动抽取落库。

### F. 文档
`docs/memory.md`（新增）、`architecture.md`（Mem0 行 → 已落地）、`README`、Phase 10 Gate 报告。

---

## 4. Definition of Done

- [ ] `user_memories` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [ ] 记忆读/写均为**幂等**，且 `(user_id, kind, key)` 唯一约束生效。
- [ ] 四个 Specialist 的 payload 均能拿到 `memory` 画像（由 RunService 统一注入）。
- [ ] `design_proposal` 在未给 `preference` 时确实使用记忆偏好（端到端断言）。
- [ ] `memory_recall` / `memory_remember` 走完整治理链（有审计行 / span）。
- [ ] 全量测试全绿（新增用例 ≥ 20）；`read_lints` 零错误。
- [ ] 文档 + Gate 报告齐备。

---

## 5. 非目标（明确未做）

- `mem0ai` 真实接入（需 LLM 抽取 + 向量库 + telemetry，无法离线确定性验证）—— 只留 `MemoryExtractor` / `MemoryStore` 协议接缝。
- 基于 LLM 的自动记忆抽取与冲突消解（规则抽取只覆盖显式关键词）。
- Redis 记忆缓存（项目明令 Redis 非业务事实源；缓存一致性属独立课题）。
- 向量化记忆检索（当前按 `kind` / `user_id` 精确召回即可；语义召回随 mem0ai 接缝一并留出）。
- 前端记忆管理页（若需要，可作为独立小课题）。
- 跨用户/跨项目的组织级记忆、记忆过期与遗忘策略（TTL / LRU）。
