# Phase 10 Gate 报告（记忆层 / Mem0）

> 结论：**PASS**。长期偏好记忆落地并**被真实消费**（同一句话、同一项目，不同用户得到不同设计风格）；
> 三个平台课题（MCP → 可观测 → **记忆**）至此全部完成。
> 日期：2026-10-05
> 范围：自建确定性记忆层（Postgres 单一事实源 + 规则抽取）；mem0ai 明确不做硬依赖，只留协议接缝。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| 契约 | `packages/schemas/src/dw_schemas/memory.py`：`MemoryKind` / `MemoryCandidate` / `MemoryItem` / `MemoryProfile`（含 `value_for` / `as_notes`）/ `MemoryUpsertIn` |
| 业务表 | `user_memories`（`uq_user_memories_user_id_kind_key`；FK → `users` **CASCADE**），Alembic `9e5f60718293` |
| 存储 | `dw_infrastructure/memory/store.py`：`MemoryStore` **协议** + `PostgresMemoryStore`（`recall` / `remember` / `forget` / `touch`，幂等 upsert + 命中计数） |
| 抽取 | `dw_infrastructure/memory/extractor.py`：`MemoryExtractor` **协议** + `RuleBasedExtractor`（确定性规则 + 否定守卫 + 一值一键） |
| 编排读 | `RunService` 执行前加载画像 → 注入 `SkillContext.memory`；`PlanRunner` 随 `RunnerConfig.memory` 下发到每个任务 |
| 编排写 | Run 结束（`_finalize` / 直连完成）从 `objective` 规则抽取 → 幂等落库（`source="run:<id>"`） |
| 受治理工具 | `memory_recall`（`memory:read`）/ `memory_remember`（`memory:write`），走完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计 / span） |
| 技能接线 | `project_snapshot` 在**有** `memory:read` 时召回记忆（§35 context loading）；`design_proposal` 在未给 `preference` 时回落记忆偏好 |
| 权限 | 新增 `memory:read` / `memory:write`，授予 5 个可发起 Run 的角色（VIEWER 不授予） |
| REST | `GET /memories`、`POST /memories`（幂等）、`DELETE /memories/{key}` |
| seed | 注册两个记忆工具（工具数 13 → 15）；`project_snapshot.allowed_tools` 增加 `memory_recall` |

---

## 2. 测试与质量

- **单元测试**：新增 `tests/unit/test_memory_layer.py`（12 例）：抽取确定性、风格同义词归一、多偏好并发抽取、**否定句不被记成肯定偏好**、正向约束（「不能延期」）不被误杀、同 key 去重、画像取值优先高置信度、工具入参边界。
- **集成测试**：新增 `tests/integration/test_memory.py`（6 例）：REST 幂等往返（重复写返回同一 id）、缺 scope 三连 403、记忆工具已注册且 `memory_recall` **进 allowed_tools 但不进 required_scopes**、Run 完成后自动抽取（含 `source` 可追溯）且时间线含 `memory_recall`、**记忆被 design_proposal 消费**、**无权用户（VIEWER）跑 supervisor 路径仍成功**。
- **全量结果**：`pytest tests/` **348 passed**（单元 213 / 集成 115 / API 契约 20），零失败；`read_lints` 零 error/warning。（Phase 9 为 330；本阶段新增 18 个用例。测试文件命名冲突——unit 与 integration 同名 `test_memory.py` 导致 pytest 收集失败——已按既有约定把 unit 文件改名为 `test_memory_layer.py`。）
- **数据库验证**：`alembic upgrade head` 后 `alembic current = 9e5f60718293 (head)`；`scripts/seed.py` 幂等执行成功（`permissions: 11` = 原 9 + 2、`tools: 2` 新插、skills/agents 就地更新）。
- **既有断言修正**：`test_agent_runs` 中「工具调用恰为 `["project_query"]`」的精确断言，按新行为改为 `["project_query", "memory_recall"]` —— 这是本阶段唯一需要改的既有断言。

---

## 3. Definition of Done 核对

- [x] `user_memories` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [x] 记忆读/写均**幂等**，`(user_id, kind, key)` 唯一约束生效（集成测试断言重复写返回同一 id）。
- [x] 四个 Specialist 的 payload / 上下文均能拿到记忆画像（由 `RunService` 统一注入，Direct 与 Plan 两条路径都覆盖）。
- [x] `design_proposal` 在未给 `preference` 时确实使用记忆偏好（端到端断言首位推荐 = 新中式）。
- [x] `memory_recall` / `memory_remember` 走完整治理链（时间线可见、审计落库、trace 可见）。
- [x] 全量测试 348 passed；`read_lints` 零错误。
- [x] 文档：`docs/memory.md`（新增）、`docs/api.md`（§2.3 + 示例）、`docs/database.md`（表 / 决策 / 迁移历史）、`architecture.md`（Mem0 行 + 落位）、`README`（相位表 / 权限数 / 工具数 / 端点 / 测试数）+ 本报告。

---

## 4. 实测结果

```
$ py -3 -m pytest tests/ -q
348 passed in 65.55s

① DESIGNER: POST /runs {intent: design_proposal, objective: "客户喜欢新中式"}
   → completed；自动落库 user_memories(style=新中式, source="run:<id>")
② 同一用户: POST /runs {intent: design_proposal, objective: "再出一套设计方案"}
   → artifact.memory_preference = "新中式"
   → artifact.recommended_styles[0].name = "新中式"
   → assumptions 含「风格偏好「新中式」取自长期记忆，本次请求未显式给出」
```

---

## 5. 关键设计决策（落地记录）

1. **幂等交给数据约束**：`(user_id, kind, key)` 唯一 + 命中即更新。应用层 `select` 再 `add` 的写法并发下会产生重复偏好，约束才是最后一道防线。
2. **自动读不抛错、自动写受 scope 约束**：没 `memory:read` 只是「少一层个性化」，不该让 Run 失败；而写入门禁统一为 `memory:write`（工具 / REST / 自动抽取**同一处门禁**，不搞例外）。
3. **project_snapshot 的记忆召回按权限门控**：以 `ctx.memory is not None` 判断，无权时**根本不调用**工具 —— 否则 VIEWER 会因为可选个性化而 Run 失败。专项反向保护测试兜住。
4. **"可以调用" ≠ "必须有权限"**：`memory_recall` 进 `allowed_tools`，不进 `required_scopes`；否则整个 supervisor 路径会被 `memory:read` 卡住。
5. **否定守卫在抽取阶段解决**：「不要新中式」不写进库，而不是「写进去再置 false」—— 后者会让存储里充满噪音，且召回时还得再判一次。
6. **一值一键**：`focus.storage` / `focus.bright` 分开，避免同 key 互相覆盖（唯一约束的必然要求）。
7. **产物标注记忆来源**：`memory_preference` + `assumptions` 明写「取自长期记忆」—— 不把「系统猜的偏好」伪装成「用户说的偏好」（provenance）。
8. **不做 Redis 缓存**：`redis.py` 已明写「禁止把 Redis 当作业务事实源」，记忆是偏好的长期事实，缓存一致性属独立课题。
9. **不需要改 Supervisor 编排核心**：记忆作为 `SkillContext` 上的一个可选字段下发，四个 Specialist 零改动即可复用。

---

## 6. 非目标（明确未做）

- `mem0ai` 真实接入（需 LLM 抽取 + 向量库 + posthog telemetry，无法离线确定性验证）—— 只留 `MemoryExtractor` / `MemoryStore` 协议接缝。
- LLM 自动抽取与冲突消解；规则抽取只覆盖显式关键词，**不做条件句与否定从句的语义分析**。
- Redis 记忆缓存、向量化记忆召回。
- 前端记忆管理页（REST 已就绪，页面属独立课题）。
- 组织级 / 跨用户记忆、记忆过期与遗忘策略（TTL / LRU）。

---

## 7. 平台课题全景（累计）

| 课题 | 状态 | 交付位置 |
|------|------|----------|
| MCP 传输层 | ✅ | `apps/mcp-server`（stdio JSON-RPC 子集，零第三方依赖） |
| 可观测与评估 | ✅ | `packages/infrastructure/observability` + `.../evaluation` |
| 记忆层（Mem0） | ✅ | `packages/infrastructure/memory` + `user_memories` + 两个受治理工具 |

三个平台课题至此全部完成。四个领域 Specialist（AfterSales / Quote / Design / Construction）
与三个平台课题（MCP / 可观测 / 记忆）构成了当前仓库的完整能力面。

---

## 8. 下一步建议（均需先对齐范围）

- **Kafka 主动式**：把领域事件（进度延期、验收缺陷、记忆命中）经 Kafka 触发主动式 Run / 通知 —— `architecture.md` 里唯一仍标未落地的主动式能力。
- **工作台补记忆页**：REST 已就绪，`apps/web` 加一页即可管理偏好（小切口，端到端可见）。
- **前端实时化**：`GET /runs/{id}/stream`（SSE）替换轮询（Phase 9 的纯 ASGI 中间件已为此留好空间）。
- **记忆层增强**：接 mem0ai 的 LLM 抽取 + 向量召回（协议接缝已就位），或补 TTL / 遗忘策略。
