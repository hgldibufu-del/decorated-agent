# 记忆层（Memory）

> 对应需求文档「长期记忆」、§35（project context loading）、Phase 10。
> 本文描述**当前仓库中真实存在的代码**，不含未实现模块。

---

## 1. 定位：与既有三层存储的分工

| 已有 | 回答什么 | 缺什么 |
|------|----------|--------|
| PostgreSQL 业务表 | 项目 / 报价 / 设计 / 施工**事实** | — |
| RAG（pgvector + BM25） | 外部**知识**证据（文档、历史案例） | — |
| Redis | 短期运行状态（`redis.py` 明写：**禁止当业务事实源**） | 不持久 |
| `agent_runs` / `audit_logs` | 发生过什么 | 不是**偏好** |
| **`user_memories`（Phase 10）** | 这位用户**长期偏好什么 / 约束什么** | — |

补上的关键能力：**跨 Run 复用**。此前每次 `design_proposal` 都需要调用方在入参里
重复给 `preference`；现在系统记得「这位客户偏好新中式」。

---

## 2. 依赖判据：为什么不自建 vs 为什么不用 mem0ai

判据与 Phase 9 一致：**确定性、可离线验证 → 真实接入；需外部服务或 LLM 判官 → 只留接缝。**

| 组件 | 现状 | 结论 |
|------|------|------|
| `mem0ai` | 可安装（2.2.1），但拖入 `openai` + `qdrant-client` + `posthog`（telemetry）+ `grpcio`；记忆抽取依赖 LLM | ❌ 不做硬依赖，留**协议接缝** |
| PostgreSQL | 已接线 | ✅ 记忆的单一事实源 |
| Redis | 已接线 | ⏸ 本轮**不做**缓存（项目明令 Redis 非事实源） |

---

## 3. 结构

### 3.1 契约（`packages/schemas/src/dw_schemas/memory.py`）

* `MemoryKind`：`preference` / `constraint` / `fact`
* `MemoryCandidate`（无 id，抽取器 / 工具 / REST 的共同输出形状）
* `MemoryItem`（已落库，带 `id` / `source` / `hits` / `last_used_at`）
* `MemoryProfile`：`value_for(key)`（置信度优先、同置信度取较新）+ `as_notes()`

### 3.2 存储与抽取（`packages/infrastructure/src/dw_infrastructure/memory/`）

| 文件 | 内容 |
|------|------|
| `models.py` | `UserMemory`（表 `user_memories`），子类化 `dw_domain.models.Base`（沿用 `rag/models.py` 先例） |
| `store.py` | `MemoryStore` **协议** + `PostgresMemoryStore`（`recall` / `remember` / `forget` / `touch`） |
| `extractor.py` | `MemoryExtractor` **协议** + `RuleBasedExtractor`（确定性规则 + 否定守卫） |

### 3.3 表

`user_memories`：`user_id`(FK→users **CASCADE**) / `kind` / `key` / `value`(JSONB) /
`confidence` / `source` / `hits` / `last_used_at`，
唯一约束 `uq_user_memories_user_id_kind_key`。

* **幂等来自数据约束**，而不是应用层判断 —— 并发下数据库拒绝第二条，
  而不是静默写出重复偏好；
* `source` 记录来源（`run:<id>` / `manual`），可回答「为什么会记得」；
* 用户注销 → CASCADE 清除，不留无法归属的偏好。

---

## 4. 读写路径

| 路径 | 触发 | 门禁 |
|------|------|------|
| **自动读** | `RunService` 执行前加载画像 → 注入 `SkillContext.memory` | `memory:read`（无权则 `None`，技能自行降级，**不报错**） |
| **自动写** | Run 结束（`_finalize` / 直连完成）→ 从 `objective` 规则抽取 → 幂等落库 | `memory:write` |
| **显式工具** | `memory_recall` / `memory_remember`（走完整治理链） | `memory:read` / `memory:write` |
| **REST** | `GET/POST/DELETE /api/v1/memories` | `memory:read` / `memory:write` |

设计取舍：

* **自动读不抛错**：没有记忆权限只是「少一层个性化」，不应让整次 Run 失败；
* **`project_snapshot` 的记忆召回按权限门控**：以 `ctx.memory is not None` 判断，
  无权时**根本不调用** `memory_recall` —— 否则只读用户（VIEWER）会因为
  「可选的个性化」而 Run 失败（有专门的反向保护测试）；
* **`memory_recall` 进 `allowed_tools` 但不进 `required_scopes`**：
  「可以调用」与「必须有权限」是两件事；
* **记忆不参与 Project ACL**：记忆是用户维度的，没有项目维度，
  硬加项目过滤只会让「用户的偏好」概念变糊。

---

## 5. 抽取规则与否定守卫

`RuleBasedExtractor` 是**纯函数**（无 IO、无随机、无 LLM），因此可离线复现、可单测。

覆盖的键：

| key | 值 | 触发词示例 |
|-----|-----|------------|
| `style` | 规范风格名（`现代简约` / `新中式` / `北欧` / `工业风`） | 新中式、简约、北欧… |
| `budget.sensitivity` | `high` | 预算有限、控制预算、性价比 |
| `material.priority` | `eco` / `premium` | 环保、无甲醛 / 进口、高端 |
| `schedule.strict` | `true` | 按期、不能延期、赶工 |
| `focus.storage` / `focus.bright` / `focus.low_maintenance` | `true` | 收纳 / 采光 / 好打理 |

两个细节：

1. **否定守卫**：匹配命中后回看**紧邻其前** 4 个字符，命中否定词（`不`/`别`/`勿`/`无`…）
   即丢弃该候选 —— 「不要新中式」不会被记成「偏好新中式」；
   而「不能延期」是**正向约束**，整串作为关键词匹配，起始位置前无疑问词，故不被误杀；
2. **一值一键**：`focus.storage` 与 `focus.bright` 各占一个 key，
   否则两个偏好会互相覆盖（唯一约束是 `(user, kind, key)`）。

---

## 6. 权限

| 权限码 | 授予角色 |
|--------|----------|
| `memory:read` | `project_manager` / `designer` / `estimator` / `construction_manager` / `aftersales`（**admin 隐式全有**） |
| `memory:write` | 同上 |

`viewer` 只有 `project:read`：不能读写记忆，但**仍可正常跑 supervisor 路径**（见 §4）。

---

## 7. 实测结果（本机，2026-10-05）

```
POST /api/v1/memories {"kind":"preference","key":"style","value":"北欧"}   → 200
POST 同上 {"value":"新中式"}                                              → 200，返回同一个 id（幂等更新）
GET  /api/v1/memories                                                    → [{"key":"style","value":"新中式","source":"manual"}]
DELETE /api/v1/memories/style                                            → {"deleted":1}
```

端到端消费（`tests/integration/test_memory.py`）：

```
① DESIGNER 发起 design_proposal，objective="客户喜欢新中式"
   → Run completed；自动抽取落库 user_memories(style=新中式, source="run:<id>")
② 同一用户再发起 design_proposal，objective="再出一套设计方案"（不提风格）
   → artifact.memory_preference = "新中式"
   → artifact.preference_used  = "新中式"
   → artifact.recommended_styles[0].name = "新中式"
   → assumptions 含「风格偏好「新中式」取自长期记忆，本次请求未显式给出」
```

**同一句话、同一项目，不同用户得到不同结果** —— 这就是记忆层要在的地方。

---

## 8. mem0ai 接缝

| 想接的能力 | 接缝 | 成本 |
|------------|------|------|
| LLM 抽取 / 冲突消解 | 实现 `MemoryExtractor.extract(text)` 协议 | 中（需 LLM Key） |
| 向量记忆检索 / 去重合并 | 实现 `MemoryStore` 协议 | 中 |
| 记忆的自动过期与遗忘 | 在 `PostgresMemoryStore` 上加 TTL / LRU 策略 | 低 |

编排侧（`RunService` / `SkillContext`）与测试只依赖协议，替换实现不必改业务代码。

---

## 9. 非目标（明确未做）

* `mem0ai` 真实接入（需 LLM 抽取 + 向量库 + telemetry，无法离线确定性验证）。
* 基于 LLM 的自动抽取与冲突消解；**规则抽取只覆盖显式关键词**，
  不做条件句（「如果预算够就…」）与否定从句的语义分析。
* Redis 记忆缓存（项目明令 Redis 非业务事实源；缓存一致性属独立课题）。
* 向量化记忆检索（当前按 `user_id` + `kind` 精确召回即可）。
* 前端记忆管理页（REST API 已就绪，可直接 curl / 测试；工作台页面属独立课题）。
* 组织级记忆、跨用户共享偏好、记忆过期与遗忘策略。
