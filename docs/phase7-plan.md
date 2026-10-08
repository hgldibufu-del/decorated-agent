# Phase 7 实施计划（Construction 施工审查 Specialist）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：Phase 4（RAG + AfterSales）、Phase 5（Quote）、Phase 6（Design）已落地并通过 Gate。

---

## 1. 落点确认（代码里已经写死的接线）

- `IntentType.CONSTRUCTION_REVIEW = "construction_review"` 已存在；`intent.py` 已把
  「施工 / 进度 / 工期 / 验收 / 延期 / 工地」路由到该意图（优先级 3、置信度 0.7）。
- `AgentType.CONSTRUCTION = "construction"` 已存在（无需改 schema）。
- `PermissionCode.CONSTRUCTION_READ = "construction:read"` **已存在**，且已授予
  `PROJECT_MANAGER` / `CONSTRUCTION_MANAGER` → **本阶段无需新增权限码**（与 Phase 5/6 不同）。
- `planner.py` 的 `MISSING_CAPABILITY_HINT` 把 **`CONSTRUCTION_REVIEW → Phase 7`** 标注，工具名为
  `progress_analysis` / `quality_check`。

Phase 7 是**最后一个领域 Specialist**：落地后 `MISSING_CAPABILITY_HINT` 将清空。

---

## 2. 推荐方案（默认，等你确认）

沿用 Phase 5/6 的**业务表驱动确定性路线**（RAG + 业务表两条路线已各验证过；Construction 补最后一个领域切片）：

### 2.1 业务表（Alembic `8d4e5f607182`，Phase 7）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `construction_milestones` | `stage`, `planned_days`, `actual_days`, `status`, `planned_start`, `actual_start`, `metadata_json` | `uq_construction_milestones_stage` |
| `quality_checklists` | `category`, `item`, `standard`, `weight`, `severity`, `metadata_json` | 检查项 + 验收标准 |

* 施工审查为**业务表驱动的确定性分析**（计划 vs 实际工期、验收项打分），可解释、可测、零外部依赖；
* `progress_analysis`：按阶段对比计划/实际工期 → 偏差、落后阶段、风险提示；
* `quality_check`：按类目评估验收项 → 通过/未通过清单、加权得分、重点缺陷。

### 2.2 工具（均 L0，`project:read` + `construction:read`）

| 工具 | 作用 |
|------|------|
| `progress_analysis` | 阶段进度对比（计划 vs 实际），产出偏差与延期风险 |
| `quality_check` | 验收项评估，产出通过清单 / 加权得分 / 缺陷 |

### 2.3 技能 + SkillRunner

* `construction_review`（L0，只读分析/合成）+ `run_construction_review`：编排
  `progress_analysis(project) → quality_check(...) →` 结构化施工审查 Artifact
  （进度总览、风险阶段、验收得分、建议、假设、置信度）。

### 2.4 Agent + 编排接线

* `construction_agent`（agent_type=construction）+ 注册 `construction_review` 技能 + 两工具。
* `planner.py`：把 `CONSTRUCTION_REVIEW` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`，新增 `_construction_plan`（单步 direct，要求可见项目）。**此时 MISSING 字典清空**。
* `skills.py`：`SKILL_RUNNERS["construction_review"] = run_construction_review`。
* `tools.py`：`BUILTIN_TOOLS` 并入 `CONSTRUCTION_TOOLS`。
* `seed.py`：幂等注册 `construction_agent` / `construction_review` / 两工具 + 默认目录（约 5 阶段 + 若干验收项）。

---

## 3. 连带影响：501 集成用例的重定位

Phase 7 落地后**不再有任何「未实现意图」**，`MISSING_CAPABILITY_HINT` 清空。现有的
`tests/integration/test_supervisor_runs.py::test_unimplemented_intent_is_501`（当前用
`construction_review` 验证 501）必须改造。建议：

* 改为回归用例：断言 `construction_review` **不再** 501（进入正常执行路径）；
* 「意图存在但能力缺失 → 501」这一约束改由**单元测试**兜底（`Planner` 在传入仅含 supervisor 的
  注册表时对未注册能力报 `UnsupportedIntentError`——现有 `test_intents_without_registered_agent_report_what_is_missing`
  与 `test_unregistered_capability_is_reported_not_silently_planned` 已覆盖，Phase 7 后其参数表清空）。

---

## 4. Definition of Done（可执行、可验证）

- [ ] `construction_milestones` / `quality_checklists` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [ ] `construction_agent` + `construction_review` + 两工具经 `scripts/seed.py` 幂等注册。
- [ ] `intent=construction_review` + 可见项目 → 路由命中 → 计划校验 → 任务 `succeeded` → 产出 `construction_review` Artifact。
- [ ] `CONSTRUCTION_REVIEW` 不再 501；`MISSING_CAPABILITY_HINT` 清空（四个领域意图全部落地）。
- [ ] 单元测试：进度分析/验收打分/技能编排/planner；集成：端到端 `construction_review`（CONSTRUCTION_MANAGER）+ 缺项目 501 + 缺 `construction:read` 403。
- [ ] `read_lints` 零 error/warning，全量测试（单元 + 集成）通过。

---

## 5. 非目标（明确未做）

- Kafka 主动式事件驱动（`architecture.md` 提到 Phase 7 做「主动式」，但本阶段只做 Construction Specialist 垂直切片；事件驱动属独立课题）。
- 基于 LLM 的自由施工评估、现场图像/影像识别。
- 施工进度的持久化写回实体（只产出 Artifact）。
- Mem0 长期记忆、真实 Reranker、MCP 传输层、OpenTelemetry/Langfuse/RAGAS（Phase 9）。

---

## 6. 文档与 Gate

- 更新 `docs/database.md`（新增施工表 + 迁移历史行）、`docs/agent-runtime.md`（§5/§7，MISSING 清空）、`docs/architecture.md`（相位表 Specialist Agent 全部落地）。
- 产出 `docs/phase7-gate-report.md`。
