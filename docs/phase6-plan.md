# Phase 6 实施计划（Design 设计提案 Specialist）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：Phase 4（RAG 底座 + AfterSales）、Phase 5（业务表驱动 + Quote）已落地并通过 Gate。

---

## 1. 落点确认（代码里已经写死的接线）

- `IntentType.DESIGN_PROPOSAL = "design_proposal"` 已存在（`dw_schemas/supervisor.py`）。
- `planner.py` 的 `MISSING_CAPABILITY_HINT` 把 **`DESIGN_PROPOSAL → Phase 6`** 标注，且工具名为
  `layout_analysis` / `style_match`。
- `AgentType.DESIGN = "design"` 已存在（`dw_schemas/agent.py`），无需改 schema。
- `intent.py`：`DESIGN_PROPOSAL` 优先级 3、默认置信度 0.7（可保留）。

Phase 6 精确 = **Design 一个 Specialist + 其业务表/技能**，Design/Construction 的「Construction」仍留 Phase 7（代码相位映射已写死）。

---

## 2. 推荐方案（默认，等你确认）

沿用 Phase 5 的**业务表驱动确定性路线**（与 Quote 同构、与 AfterSales 的 RAG 路线并列，再次证明「两种数据源都能挂进同一骨架」）：

### 2.1 业务表（Alembic `7c3d4e5f6071`，Phase 6）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `design_styles` | `name`, `description`, `characteristics(JSONB)`, `suitable_layouts`, `palette`, `tags` | `uq_design_styles_name` |
| `layout_modules` | `room_type`, `suggested_function`, `design_principle`, `recommended_material_category`, `notes` | 按 `room_type` 定向检索 |

* 金额无关；`palette`/`characteristics`/`tags` 用 `JSONB`（真正动态结构）。
* `layout_analysis`：根据项目房屋的 `layout`（户型）+ `area_sqm`，匹配 `layout_modules` 并产出空间规划建议（确定性规则：户型 token → 模块建议 + 面积分区提示）。
* `style_match`：根据偏好风格（或默认）与约束，从 `design_styles` 匹配并排序出推荐风格。

### 2.2 工具（均 L0，`project:read` + `design:read`）

| 工具 | 作用 |
|------|------|
| `layout_analysis` | 基于户型/面积产出空间规划建议（取 `Project→House` + `layout_modules`） |
| `style_match` | 按偏好/约束匹配并排序设计风格（取 `design_styles`） |

### 2.3 技能 + SkillRunner

* `design_proposal`（L0，只读合成，不产生业务写操作）+ `run_design_proposal`：编排
  `layout_analysis(project) → style_match(preference) →` 结构化提案 Artifact
  （空间建议、推荐风格、色板、建议材料类目、假设、置信度）。

### 2.4 Agent + 编排接线

* `design_agent`（agent_type=design）+ 注册 `design_proposal` 技能 + 两工具。
* `planner.py`：把 `DESIGN_PROPOSAL` 从 `MISSING_CAPABILITY_HINT` 移入 `INTENT_CAPABILITY`，新增 `_design_plan`（单步 direct，要求可见项目）。
* `skills.py`：`SKILL_RUNNERS["design_proposal"] = run_design_proposal`。
* `tools.py`：`BUILTIN_TOOLS` 并入 `DESIGN_TOOLS`。
* `seed.py`：幂等注册 `design_agent`/`design_proposal`/两工具 + 默认目录（约 3 风格 + 若干户型模块）。

### 2.5 权限扩展（与 Phase 4/5 一致）

* `PermissionCode` 新增 `DESIGN_READ = "design:read"`（seed 自动枚举入库）。
* `rbac_defaults`：授予 `DESIGNER` + `PROJECT_MANAGER`（`ADMIN` 自动全权）。
* 集成测试用 `DESIGNER` 角色（天然含 `design:read` + `project:read`）验证 scope 链路与 ACL。

---

## 3. Definition of Done（可执行、可验证）

- [ ] `design_styles` / `layout_modules` 随 `alembic upgrade head` 创建成功（真实 PG 验证）。
- [ ] `design_agent` + `design_proposal` + 两工具经 `scripts/seed.py` 幂等注册。
- [ ] `intent=design_proposal` + 可见项目 → 路由命中 → 计划校验 → 任务 `succeeded` → 产出 `design_proposal` Artifact（含空间建议/推荐风格/色板）。
- [ ] `DESIGN_PROPOSAL` 不再 501；`construction_review` 仍明确 501 并说明 Phase 7。
- [ ] 单元测试：布局匹配/风格排序/技能编排/planner；集成：端到端 `design_proposal`（DESIGNER）+ 缺项目 501 + ACL 403。
- [ ] `read_lints` 零 error/warning，全量测试（单元 + 集成）通过。

---

## 4. 非目标（明确未做）

- Construction Specialist（Phase 7）。
- 基于 LLM 的「自由生成式」设计图/渲染（本阶段用确定性业务表合成，可解释、可测、零外部依赖）。
- 正式设计合同/方案的持久化写回实体（只产出 Artifact）。
- 真实风格图谱、3D 布局自动生成、Memo 长期记忆等。

---

## 5. 备选：RAG 驱动（非默认）

若你更想**证明 Phase 4 的 RAG 底座可跨领域复用**，Phase 6 可改为 RAG 路线：
复用 `rag_documents`/`rag_document_chunks` + `DocumentStore`，seed 一批设计知识（风格库、户型原则、案例），
`layout_analysis`/`style_match` 改为混合检索。优点：验证 RAG 基础设施领域无关；
代价：需准备设计语料、测试断言偏「检索命中」而非「精确数值」。

---

## 6. 文档与 Gate

- 更新 `docs/database.md`（新增设计表 + 迁移历史行）、`docs/agent-runtime.md`（§5/§7）、`docs/architecture.md`（相位表）。
- 产出 `docs/phase6-gate-report.md`。
