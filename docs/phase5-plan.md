# Phase 5 实施计划（报价估算 Specialist 落地）

> 状态：草案（待确认）
> 依据：`architecture.md` 相位表、`agent-runtime.md §5`、Phase 4 Gate 报告推荐、以及 `planner.py` 中已写死的相位映射
> `QUOTE_ESTIMATE → Phase 5 / DESIGN_PROPOSAL → Phase 6 / CONSTRUCTION_REVIEW → Phase 7`。
>
> 结论先行：**Phase 5 精确 = 落地 Quote（报价估算）这一个 Specialist + 它的业务表**。
> Design / Construction 严格留给 Phase 6 / Phase 7，不在本阶段范围。

---

## 0. 为什么只做 Quote（且正好契合现有相位映射）

- `IntentType.QUOTE_ESTIMATE`、`AgentType.QUOTE`、`PermissionCode.QUOTE_READ/QUOTE_WRITE` 已在仓库中存在（占位/权限已就绪）。
- 意图路由 `intent.py` 已能命中「报价 / 预算 / 套餐 / 多少钱」等关键词（`test_intent_router.py` 已有用例）。
- `planner.py` 的 `MISSING_CAPABILITY_HINT` 把 `QUOTE_ESTIMATE` 明确标为 **Phase 5**；`DESIGN_PROPOSAL` 标 Phase 6、`CONSTRUCTION_REVIEW` 标 Phase 7。
- 报价是装修业务价值链最前、最高频、最易量化 ROI 的 Specialist，业务表（套餐/工艺项/单价）结构清晰、可确定性计算、易测试。
- 与 Phase 4 的 AfterSales 试点一样，采用**单一垂直切片**：一个新 AgentType + 它的 Skill/Tool + 一个 SkillRunner，**不新增编排代码**。

---

## 1. 范围

### 必做（构成 Phase 5 垂直切片）
1. **业务表（新增，落在 `packages/domain/models/`，纳入 Alembic）**
   - `quote_packages`（套餐）：`name`、`description`、`tier`（经济/标准/高端）、`base_price NUMERIC(12,2)`（基础费）、`price_per_sqm NUMERIC(12,2)`（单价）、`included_scope JSONB`、`metadata_json`。
   - `quote_items`（工艺/材料项）：`category`（硬装/主材/软装…）、`name`、`unit`（m²/项/米…）、`unit_price NUMERIC(12,2)`、`metadata_json`。
   - （可选）`quote_package_items` 关联套餐与工艺项；本阶段为保持最小，先**不建**关联表，套餐用 `price_per_sqm + base_price` 表达，工艺项用于明细拆解。
2. **三个 Quote 工具（RAG 之外的「业务表驱动」确定性工具，全部 L0、scope `quote:read` + `project:read`）**
   - `budget_estimate`：入参 `{project_id, package_id?, notes?}` → 加载 `Project→House`（取 `area_sqm`、`layout`）→ 选套餐 → 计算明细（基础费 + 面积×单价 + 工艺项增项）→ 返回 `line_items[]`、`total`(Decimal→str)、`assumptions`、`confidence`。
   - `package_compare`：入参 `{area_sqm, packages?: list[str], requirements?}` → 对 2–3 个套餐计算总价与每平米单价 → 返回排序对比。
   - `material_lookup`：入参 `{category?, keyword}` → 精确/模糊检索 `quote_items` → 返回匹配工艺/材料项及单价。
3. **Skill `quote_estimate`（L0，只读估算）** + **SkillRunner `run_quote_estimate`**
   - 编排：取项目上下文 → `budget_estimate`（推套餐）→ `package_compare`（同面积多套餐对比）→ `material_lookup`（关键类目）。
   - 产出带引用的 Artifact `quote_estimate`：`recommended_package`、`estimate{line_items,total,currency}`、`comparison[]`、`materials[]`、`assumptions`、`confidence`。
4. **Agent `quote_agent`**（`agent_type=quote`）注册 + seed。
5. **Planner 接线**：把 `QUOTE_ESTIMATE` 从 `MISSING_CAPABILITY_HINT` 挪入 `INTENT_CAPABILITY`（→ `quote_agent`/`quote_estimate`）；新增 `_quote_plan`（单步 direct；**要求可见项目**，无项目则明确报错，与 `project_overview` 一致）。
6. **Alembic 迁移**：新增两张表（落在 `5a1b2c3d4e5f` 之后）。
7. **测试**
   - 单元：`budget_estimate` 金额计算（Decimal 精度）、`package_compare` 排序、`material_lookup` 检索、`run_quote_estimate` 编排（FakeExecutor）；更新 `test_planner.py` 把 `QUOTE_ESTIMATE` 移出「缺失意图」参数表。
   - 集成：迁移 + 端到端 `POST /runs intent=quote_estimate`（带 house 面积的项目）→ `completed` + Artifact 含 `estimate.total`；更新 `test_unsupported_intent_is_501` 改用仍是 Phase 6 的 `design_proposal`。
8. **文档**：`database.md`（报价表）、`agent-runtime.md §5`（quote 已注册）、`architecture.md`（Phase 5 状态）。

### 非目标（明确不做，留给后续 Phase）
- **Design / Construction Specialist**（Phase 6 / 7）——即便代码里已占位，本阶段不落地。
- 正式报价单的**持久化写回实体**（本阶段只产出 Artifact，不改写业务报价表以外的事实）。
- 税费、折扣、阶梯价、区域系数等复杂计价引擎（先用 `基础费 + 面积×单价 + 工艺项` 足够演示）。
- 基于 LLM 的自由报价生成（本阶段用确定性业务表计算，可解释、可测、零外部依赖）。
- Mem0 长期偏好、Kafka/Redis 主动场景、真实 Reranker、MCP 传输层（同 Phase 4 非目标）。

---

## 2. Definition of Done

- [ ] `quote_packages` / `quote_items` 两表随 `alembic upgrade head` 创建成功（CI 可在真实 PG 验证）。
- [ ] `quote_agent` + `quote_estimate` + 三个工具经 `scripts/seed.py` 注册（或测试内 `ensure_*`）。
- [ ] 提交 `intent=quote_estimate` 且带可见项目 → 路由命中 → 计划校验通过 → 任务 `succeeded` → 产出 `quote_estimate` Artifact，且 `estimate.total` 为字符串（Decimal 精度无损）。
- [ ] 金额全程 `Decimal`，序列化用字符串，无 float 舍入（满足 `project.py` 的金额约束）。
- [ ] `QUOTE_ESTIMATE` 不再返回 501；`design_proposal` / `construction_review` 仍明确 501 并说明各自 Phase。
- [ ] 单元测试 + 集成测试全绿（`pytest tests/unit tests/integration`）。
- [ ] `read_lints` 零 error/warning。
- [ ] `docs/phase5-gate-report.md` 落定结论。

---

## 3. 关键技术决策（待你拍板）

| 决策点 | 推荐 | 备选 |
|--------|------|------|
| Quote 风险等级 | **L0**（只读估算，不产生业务写操作，与 `project_snapshot` 一致） | L1（与 AfterSales 对齐，但 Quote 本阶段只读，L0 更贴切） |
| 业务表深度 | **最小**：`quote_packages` + `quote_items` 两张，套餐用 `base_price + price_per_sqm` | 含 `quote_package_items` 关联表（更真实但更重） |
| 默认目录数据 | **seed 一小套**（3 套餐 + 若干工艺项）使能力开箱可用；测试另插作用域数据并自清 | 仅测试内插入，seed 不落业务数据 |
| 面积/户型来源 | 复用已有 `Project→House.area_sqm/layout`，不新增项目字段 | 由 objective 解析（脆弱，不推荐） |

---

## 4. 与 Phase 4 的复用

- 完全复用：`SkillRunner` 分发机制、`ToolExecutor` 治理链、`Planner`/`DAG`/`Reviewer`、`SkillContext`、`RegistryRepository.ensure_*`、Alembic/PG 接入方式。
- 不复用 RAG：Quote 是**业务表驱动**的确定性计算（与 AfterSales 的 RAG 证据底座形成对照，验证「两种 Specialist 数据源」都能挂进同一编排骨架）。
- 金额处理复用 `project.py` 既定的 `Decimal`/字符串规则。
