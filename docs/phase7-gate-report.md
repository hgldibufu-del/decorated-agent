# Phase 7 Gate 报告（Construction 施工审查 Specialist）

> 结论：**PASS**。§5 的四个领域 Specialist 至此全部落地，`MISSING_CAPABILITY_HINT` 清空。
> 日期：2026-10-05
> 范围：落地 Construction 这一个 Specialist + 两张业务表，复用 Phase 5/6 的「业务表驱动」路线。

---

## 1. 本次交付（相对 Phase 6）

| 类别 | 交付 |
|------|------|
| 业务表 | `construction_milestones`（按项目、FK → projects CASCADE）/ `quality_checklists`（全局验收模板），Alembic `8d4e5f607182` |
| 工具 | `progress_analysis` / `quality_check`（均 L0，`construction:read` + `project:read`） |
| Skill | `construction_review`（L0，只读分析/合成，不产生业务写操作） + `run_construction_review` SkillRunner |
| Agent | `construction_agent`（agent_type=construction） |
| 权限 | **复用**既有 `PermissionCode.CONSTRUCTION_READ`（Phase 1 已定义、已授予 `PROJECT_MANAGER` / `CONSTRUCTION_MANAGER`）——本阶段无需新增权限码 |
| 编排接线 | `planner.py`：`CONSTRUCTION_REVIEW` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`，新增 `_construction_plan`（单步 direct，要求可见项目）；**MISSING 清空** |
| seed | 标准 5 阶段模板 + 6 验收项 + 按项目状态生成阶段进度 + 注册表幂等写入 |

---

## 2. 测试与质量

- **单元测试**：新增 `test_construction_tools.py`（进度偏差/风险分析、验收加权打分纯逻辑 + 技能编排 + 调用顺序 + 缺参校验）；`test_planner.py` 增补 `construction_registries()` 与 Construction 用例，并把「缺失意图」参数化用例改为 `test_all_domain_intents_are_implemented`（断言 `MISSING_CAPABILITY_HINT == {}` 且四意图均已登记）。
- **集成测试**：新增 `test_construction.py`：端到端 `construction_review`（CONSTRUCTION_MANAGER，计划合计 31 / 已完成实际 20 / 泥瓦延期 3 天 → `at_risk`）、缺项目 501、缺 `construction:read`（VIEWER）403。
- **全量结果**：单元 174 passed、集成 111 passed，**合计 285 passed**（Phase 6 为 273）；`read_lints` 零 error/warning。
- **数据库验证**：`alembic upgrade head` 后 `alembic current = 8d4e5f607182 (head)`；`scripts/seed.py` 幂等执行成功（`construction_milestones: 25` = 5 项目 × 5 阶段、`quality_checklists: 4` 新插、`permissions: 9` 不变）。
- **回归**：`test_unimplemented_intent_is_501` 重定位为 `test_construction_review_no_longer_501`（四个领域意图全部落地后，已无「未实现意图」可触发 501；该契约改由 Planner 单测兜底）。

---

## 3. Definition of Done 核对

- [x] `construction_milestones` / `quality_checklists` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [x] `construction_agent` + `construction_review` + 两工具经 `scripts/seed.py` 幂等注册。
- [x] `intent=construction_review` + 可见项目 → 路由命中 → 计划校验 → 任务 `succeeded` → 产出 `construction_review` Artifact。
- [x] `CONSTRUCTION_REVIEW` 不再 501；`MISSING_CAPABILITY_HINT` 清空（四个领域意图全部落地）。
- [x] 单元 + 集成全绿；`read_lints` 零 error/warning。

---

## 4. 关键设计决策（落地记录）

1. **单一垂直切片**：Phase 7 只做 Construction（最后一个领域 Specialist）。
2. **per-project 里程碑**：`construction_milestones` 按项目存储（FK → projects CASCADE），比「全局模板 + 从项目状态臆测进度」更诚实；`progress_analysis` 读取该项目自身阶段，缺失时安全返回空计划。
3. **验收模板全局、评估按权重**：`quality_checklists` 为全局标准；`quality_check` 以「通过项权重 / 总权重」给分，未报告缺陷即满分（保留实测结果接缝）。
4. **复用权限码**：`construction:read` 早在 Phase 1 的 RBAC 矩阵中定义，本阶段直接复用，未新增权限码（与 Phase 5/6 不同）。
5. **L0 只读**：施工审查不产生业务写操作，与其它 Specialist 一致，免审批、易验证。

---

## 5. 非目标（明确未做）

- Kafka 主动式事件驱动（`architecture.md` 提及 Phase 7 做「主动式」；本阶段只交付 Construction 垂直切片，事件驱动为独立课题）。
- 基于 LLM 的自由施工评估、现场图像/影像识别。
- 施工进度的持久化写回实体（只产出 Artifact）。
- Mem0 长期记忆、真实 Reranker、MCP 传输层、OpenTelemetry/Langfuse/RAGAS（Phase 9）。

---

## 6. 编排骨架收口（累计）

| Phase | Specialist | 数据源路线 | 代表工具 |
|-------|-----------|-----------|----------|
| 4 | AfterSales | RAG 证据检索（pgvector + BM25 + RRF） | `case_search` / `root_cause` / `case_match` |
| 5 | Quote | 业务表驱动（确定性计算，Decimal 金额） | `budget_estimate` / `package_compare` / `material_lookup` |
| 6 | Design | 业务表驱动（确定性合成，JSONB） | `layout_analysis` / `style_match` |
| 7 | Construction | 业务表驱动（确定性分析 + 加权打分） | `progress_analysis` / `quality_check` |

结论：同一 Supervisor 编排骨架承载了 **RAG + 业务表两条数据源路线 / 四个领域 Specialist**，编排核心零改动；`MISSING_CAPABILITY_HINT` 由「占位四个 Phase」收敛为空结构（保留供未来能力缺失时声明 Phase）。

---

## 7. 下一步建议

四个领域 Specialist 已收口。后续可选方向（均需先对齐范围）：

- **Kafka 主动式**：把领域事件（如进度延期、验收缺陷）经 Kafka 触发主动式 Run/通知（`architecture.md` 的 Phase 7 主动式）。
- **记忆层（Mem0）**：长期用户偏好/项目上下文，供各 Specialist 复用。
- **可观测与评估（Phase 9）**：OpenTelemetry / Langfuse / RAGAS 接入。
- **MCP 传输层**：`apps/mcp-server`，令 `ToolDefinition` 可跨进程暴露。
