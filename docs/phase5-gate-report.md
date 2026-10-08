# Phase 5 Gate 报告（Quote 报价估算 Specialist）

> 结论：**PASS**，可进入 Phase 6（Design Specialist）。
> 日期：2026-10-05
> 范围：落地 Quote 这一个 Specialist + 两张业务表，复用 Phase 4 的 RAG 之外的「业务表驱动」路线。

---

## 1. 本次交付（相对 Phase 4）

| 类别 | 交付 |
|------|------|
| 业务表 | `quote_packages` / `quote_items`（Alembic `6b2c3d4e5f60`，`NUMERIC(12,2)` + `JSONB`） |
| 工具 | `budget_estimate` / `package_compare` / `material_lookup`（均 L0，`quote:read` + `project:read`） |
| Skill | `quote_estimate`（L0，只读估算，不产生业务写操作） + `run_quote_estimate` SkillRunner |
| Agent | `quote_agent`（agent_type=quote） |
| 编排接线 | `planner.py`：`QUOTE_ESTIMATE` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`，新增 `_quote_plan`（单步 direct，要求可见项目） |
| seed | 默认 3 套餐 + 5 工艺/材料项 + 注册表幂等写入 |
| 治理修复 | `execute_plan` 补上 Agent/Skill 的 scope 预校验（与直连 `execute()` 一致），缺权直接 403 而非创建注定失败的 Run |

---

## 2. 测试与质量

- **单元测试**：新增 `test_quote_tools.py`（金额计算 / 套餐排序 / 材料检索纯逻辑）、`test_quote_skill.py`（技能编排 + 调用顺序 + 缺参校验）；`test_planner.py` 增补 Quote 正向用例并将 `QUOTE_ESTIMATE` 移出「缺失意图」参数表。
- **集成测试**：新增 `test_quote.py`：端到端 `quote_estimate`（ESTIMATOR，面积 100 × 标准单价 1280 + 基础 28000 = 156000.00）、缺项目 501、跨用户 ACL 403。
- **全量结果**：单元 156 passed，集成 85 passed（含修复后 ACL 用例）；`read_lints` 零 error/warning。
- **回归**：原 `test_unimplemented_intent_is_501` 改用仍是 Phase 6 的 `design_proposal`；AfterSales / 概览 / 对比等既有意图测试全绿。

---

## 3. Definition of Done 核对

- [x] `quote_packages` / `quote_items` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [x] `quote_agent` + `quote_estimate` + 三工具经 `scripts/seed.py` 幂等注册。
- [x] `intent=quote_estimate` + 可见项目 → 路由命中 → 计划校验 → 任务 `succeeded` → 产出 `quote_estimate` Artifact，`estimate.total` 为字符串（Decimal 精度无损）。
- [x] 金额全程 `Decimal`，序列化用字符串，无 float 舍入。
- [x] `QUOTE_ESTIMATE` 不再 501；`design_proposal` / `construction_review` 仍明确 501 并说明各自 Phase。
- [x] 单元 + 集成全绿；`read_lints` 零 error/warning。

---

## 4. 关键设计决策（落地记录）

1. **单一垂直切片**：Phase 5 只做 Quote，Design/Construction 严格留给 Phase 6/7（代码里相位映射已写死：`QUOTE_ESTIMATE→Phase 5 / DESIGN_PROPOSAL→Phase 6 / CONSTRUCTION_REVIEW→Phase 7`）。
2. **业务表驱动 vs RAG**：Quote 走确定性计算（`基础费 + 面积×单价`），与 AfterSales 的 RAG 证据路线形成对照，验证「两种 Specialist 数据源」都能挂进同一 Supervisor 编排骨架，无需新编排代码。
3. **面积/户型来源**：复用既有 `Project→House.area_sqm/layout`，不新增项目字段；`budget_estimate` 经 `ProjectRepository.find_access` + `can_read_project` 严格走 Project ACL。
4. **L0 只读**：报价估算不产生业务写操作，与 `project_snapshot` 一致，免审批、易验证。

---

## 5. 非目标（明确未做）

- Design / Construction Specialist（Phase 6 / 7）。
- 正式报价单的持久化写回实体（本阶段只产出 Artifact）。
- 税费 / 折扣 / 阶梯价 / 区域系数等复杂计价引擎（用 `基础费 + 面积×单价 + 工艺项` 足够演示）。
- 基于 LLM 的自由报价生成（本阶段用确定性业务表计算，可解释、可测、零外部依赖）。
- Mem0 / Kafka / Redis 主动场景 / 真实 Reranker / MCP 传输层（同 Phase 4 非目标）。

---

## 6. 治理修复说明（顺带）

测试暴露一个 §12 治理链缺口：`execute_plan`（意图执行路径）此前未在执行前预校验 Agent/Skill 的 `required_scopes`，导致缺权用户请求被接受（201）后又在工具调用阶段失败。本次补齐与直连 `execute()` 一致的 scope 预校验，使缺权直接 403——这是权限应在治理链最前端拦截的正确行为，且对既有意图（overview/compare/aftersales 均由具备 `project:read` 的角色发起）无副作用。

---

## 7. 下一步建议

**Phase 6 = Design（设计提案）Specialist**：同理落地 `design_agent` + `design_proposal` 技能 + 设计类工具（如 `layout_analysis` / `style_match`），并补齐对应业务表或 RAG 证据；把 `DESIGN_PROPOSAL` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`。
