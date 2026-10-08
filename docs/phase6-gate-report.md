# Phase 6 Gate 报告（Design 设计提案 Specialist）

> 结论：**PASS**，可进入 Phase 7（Construction Specialist）。
> 日期：2026-10-05
> 范围：落地 Design 这一个 Specialist + 两张业务表，复用 Phase 5 的「业务表驱动」路线（与 Phase 4 的 RAG 路线并列）。

---

## 1. 本次交付（相对 Phase 5）

| 类别 | 交付 |
|------|------|
| 业务表 | `design_styles` / `layout_modules`（Alembic `7c3d4e5f6071`，`JSONB` 动态结构，金额无关） |
| 工具 | `layout_analysis` / `style_match`（均 L0，`design:read` + `project:read`） |
| Skill | `design_proposal`（L0，只读分析/合成，不产生业务写操作） + `run_design_proposal` SkillRunner |
| Agent | `design_agent`（agent_type=design） |
| 权限 | `PermissionCode` 新增 `DESIGN_READ = "design:read"`；`rbac_defaults` 授予 `DESIGNER` + `PROJECT_MANAGER` |
| 编排接线 | `planner.py`：`DESIGN_PROPOSAL` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`，新增 `_design_plan`（单步 direct，要求可见项目） |
| seed | 默认 4 风格 + 6 户型模块 + 注册表幂等写入（`design_styles` / `layout_modules` 计数器） |

---

## 2. 测试与质量

- **单元测试**：新增 `test_design_tools.py`（房间推导 / 模块筛选 / 风格打分排序纯逻辑 + 技能编排 + 调用顺序 + 缺参校验）；`test_planner.py` 增补 `design_registries()` 与 Design 正向用例，并将 `DESIGN_PROPOSAL` 移出「缺失意图」参数表。
- **集成测试**：新增 `test_design.py`：端到端 `design_proposal`（DESIGNER，户型 三室两厅 / 面积 100.00 → 空间规划 + 风格推荐 + 色板）、缺项目 501、缺 `design:read`（VIEWER）跨权限 403。
- **全量结果**：单元 165 passed、集成 108 passed，**合计 273 passed**（Phase 5 为 229）；`read_lints` 零 error/warning。
- **数据库验证**：`alembic upgrade head` 后 `alembic current = 7c3d4e5f6071 (head)`；`scripts/seed.py` 幂等执行成功（`permissions: 9`、`design_styles: 2` 新插，证明按名去重生效）。
- **回归**：原 `test_unimplemented_intent_is_501` 改用仍属 Phase 7 的 `construction_review`；Quote / AfterSales / 概览 / 对比等既有意图测试全绿。

---

## 3. Definition of Done 核对

- [x] `design_styles` / `layout_modules` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [x] `design_agent` + `design_proposal` + 两工具经 `scripts/seed.py` 幂等注册。
- [x] `intent=design_proposal` + 可见项目 → 路由命中 → 计划校验 → 任务 `succeeded` → 产出 `design_proposal` Artifact（含空间建议 / 推荐风格 / 色板）。
- [x] `DESIGN_PROPOSAL` 不再 501；`construction_review` 仍明确 501 并说明 Phase 7。
- [x] 单元 + 集成全绿；`read_lints` 零 error/warning。

---

## 4. 关键设计决策（落地记录）

1. **单一垂直切片**：Phase 6 只做 Design，Construction 严格留给 Phase 7（代码里相位映射已写死：`QUOTE_ESTIMATE→Phase 5 / DESIGN_PROPOSAL→Phase 6 / CONSTRUCTION_REVIEW→Phase 7`）。
2. **业务表驱动 vs RAG**：Design 走确定性合成（户型模块匹配 + 风格打分），与 Quote 同构、与 AfterSales 的 RAG 路线并列，二次验证「两种 Specialist 数据源」都能挂进同一 Supervisor 编排骨架，无需新编排代码。
3. **户型/面积来源**：复用既有 `Project→House.area_sqm/layout`，不新增项目字段；`layout_analysis` 经 `ProjectRepository.find_access` + `can_read_project` 严格走 Project ACL。
4. **独立 read scope**：与 Phase 4/5 一致，为 Design 引入 `design:read`，避免复用 `project:read` 造成「专业能力」与「项目可见性」授权语义混同。
5. **L0 只读**：设计提案不产生业务写操作，与 `project_snapshot` / `quote_estimate` 一致，免审批、易验证。
6. **户型解析兜底（测试驱动修正）**：`_select_modules` 初版仅在命中为空时回退，但 baseline 房间类型（厨/卫/阳）永不为空，导致无法解析的户型被错误收窄。修正为「户型完全解析不出（derived 仅含住宅标配）时回退全部模块」，使兜底真正生效。

---

## 5. 非目标（明确未做）

- Construction Specialist（Phase 7）。
- 基于 LLM 的自由生成式设计方案 / 渲染图（本阶段用确定性业务表合成，可解释、可测、零外部依赖）。
- 正式设计合同的持久化写回实体（只产出 Artifact）。
- 真实风格图谱、3D 布局自动生成、Memo 长期记忆、真实 Reranker / MCP 传输层（同 Phase 4/5 非目标）。

---

## 6. 数据源路线全景（累计）

| Phase | Specialist | 数据源路线 | 代表工具 |
|-------|-----------|-----------|----------|
| 4 | AfterSales | RAG 证据检索（pgvector + BM25 + RRF） | `case_search` / `root_cause` / `case_match` |
| 5 | Quote | 业务表驱动（确定性计算，Decimal 金额） | `budget_estimate` / `package_compare` / `material_lookup` |
| 6 | Design | 业务表驱动（确定性合成，JSONB） | `layout_analysis` / `style_match` |

结论：同一 Supervisor 编排骨架已成功承载 **两种数据源路线 / 三个 Specialist**，未改动编排核心。

---

## 7. 下一步建议

**Phase 7 = Construction（施工审查）Specialist**：同理落地 `construction_agent` + `construction_review` 技能 + 施工类工具（如 `progress_analysis` / `quality_check`），补齐对应业务表或 RAG 证据，并把 `CONSTRUCTION_REVIEW` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`——届时 `MISSING_CAPABILITY_HINT` 将清空。
