# 工作台下半场实施计划（写操作 UI + 实时时间线 + 运行历史后端化）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：前端工作台（apps/web）已交付；后端 Phase 0-7 已就绪。

---

## 1. 现状约束（决定方案的关键事实）

1. **Run 同步执行**：`POST /api/v1/runs` 在请求内**同步**跑完整个 Run（`RunService.execute_intent` 直接 await），
   worker/Celery 未落地（`apps/worker` 属后续 Phase）。因此「运行中」几乎没有可流式的真实时间窗——
   响应返回时 Run 通常已终态。
2. **无参考数据端点**：路由只有 `auth/health/projects/registry/runs`。**没有** customers / houses / users
   的查询或创建端点，仓库层也没有 list 方法。所以「新建项目」（需 customer_id + house_id）、
   「加成员」（需候选 user_id）在 UI 上**无法落地**，必须先补端点。
3. 审批闭环（approve/reject + resume）在后端与工作台已具备，本阶段只需补齐入口与体验。

---

## 2. 交付范围（三块）

### A. 运行历史后端化（干净、无争议）

* 后端：`RunRepository.list_for_requester(user_id, *, is_admin, limit)`（按 `created_at desc`；admin 见全部，其余按 `requester_id` 收敛）。
* 端点：`GET /api/v1/runs?limit=`（默认 20，上限 100）→ `list[RunOut]`。
* 前端：工作台「运行历史」改为读后端；**后端不可用时回退本地记录**（保留 `api/history.ts` 作兜底）。
* 测试：仓储/端点集成（requester 收敛 + admin 全量 + limit）；前端 store 单测。

### B. 写操作 UI（含最小参考数据端点）

* 后端新增（均需 `project:write`，与 `POST /projects` 一致）：
  * `GET /api/v1/customers`、`POST /api/v1/customers`；
  * `GET /api/v1/houses?customer_id=`、`POST /api/v1/houses`；
  * `GET /api/v1/users`（成员候选：id/email/full_name，最小字段）。
* 前端：
  * 项目页「**新建客户 / 新建房屋 / 新建项目**」表单（客户 → 房屋 → 项目，串起来才可用）；
  * 项目详情「**添加成员**」（选用户 + 角色）；
  * 工作台审批区已具备 approve/reject，本阶段补「审批后状态刷新 + 历史入口」。

### C. 实时时间线（方案待定，见确认问题）

约束见 §1.1。三种做法：
* **前端轮询（推荐）**：Run 非终态时每秒 `GET /runs/{id}/events`，终态停止。零后端流式改动，
  无 SSE 鉴权问题（`EventSource` 不能带 `Authorization` 头），对用户观感等价。
* **真·SSE + 后台执行**：把 Run 执行改为后台任务（独立 DB 会话），`POST /runs` 立即返回 `running`，
  `GET /runs/{id}/stream` 用 SSE 推送直到终态。名副其实，但改动核心执行模型（会话生命周期 / 并发 / 测试）。
* **SSE 回放式**：新增 `GET /runs/{id}/stream`，把已有事件以 SSE 帧回放后关闭。对已终态 Run 意义有限。

---

## 3. Definition of Done

- [ ] `GET /runs` 按 requester 收敛（admin 全量），前端历史来自后端、后端不可用时回退本地。
- [ ] 可在 UI 完成「新建客户 → 新建房屋 → 新建项目」与「添加成员」闭环。
- [ ] 时间线按所选方案实现（轮询 / SSE），Run 终态后停止刷新。
- [ ] 后端：新增端点单测 + 集成测试全绿；前端：`typecheck` / `test` / `build` 全绿。
- [ ] `read_lints` 零错误；更新 `docs/`（api / database / web-workbench）与本阶段 Gate 报告。

---

## 4. 非目标（明确未做）

- worker / Celery 异步执行框架（除非实时时间线选「真·SSE + 后台执行」）。
- 项目 / 客户 / 房屋的**编辑与删除**（只做新建与查询）。
- 用户账号的创建与管理（仅提供成员候选查询）。
- 国际化 / 移动端深度适配。
