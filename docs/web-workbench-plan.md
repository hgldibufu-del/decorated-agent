# 前端工作台实施计划（apps/web）

> 状态：草案，待确认后执行。
> 日期：2026-10-05
> 依赖：后端 Phase 0-7 已就绪（Auth / Project ACL / Registry / Runs / Artifacts 全部可用）。

---

## 1. 现状与目标

**现状**：`apps/web` 目前只有一个 `HealthView.vue`（Phase 0 工程骨架）——没有登录、项目、工作台、注册中心入口。后端四个领域 Specialist 已全部落地，但用户侧**看不见也点不到**。

**目标**：把 `apps/web` 补成可用工作台，让「登录 → 选项目 → 自然语言 → 看计划 → 执行 → 看时间线 → 看 Artifact」端到端跑通。

---

## 2. 已就绪的后端契约（本阶段预计不改业务）

| 能力 | 端点 | 关键形状 |
|------|------|----------|
| 登录 | `POST /api/v1/auth/login` | `{email,password}` → `{access_token,token_type,expires_in}` |
| 当前用户 | `GET /api/v1/auth/me` | `UserSummary{id,email,full_name,roles[],permissions[]}` |
| 项目列表 | `GET /api/v1/projects` | `ProjectSummary[]`（按 ACL 收敛） |
| 项目详情 | `GET /api/v1/projects/{id}` | `ProjectDetail`（含 customer/house/members） |
| 注册中心 | `GET /api/v1/agents` `/skills` `/tools` | 只读 |
| 预览计划 | `POST /api/v1/runs/plan` | `{message,project_id}` → `Plan{intent,mode,steps[],rationale}` |
| 发起 Run | `POST /api/v1/runs` | `{intent|agent_id+skill_id,objective,project_id,input}` → `RunOut` |
| Run 详情/时间线/工具 | `GET /api/v1/runs/{id}`、`/events`、`/tool-calls` | `RunOut` / `RunEvent[]` / `ToolCallOut[]` |
| Artifact | `GET /api/v1/artifacts/{id}` | `{artifact_type,producer,payload,version}` |
| 审批 | `POST /api/v1/approvals/{id}/approve|reject`、`/runs/{id}/resume` | 决策 + 留痕 |

所有错误统一为 `{code,message,request_id,retryable,category,details}`（前端 `ApiClient` 已能解析）。

---

## 3. 交付范围（推荐）

### 3.1 基础设施
* 扩展 `ApiClient`：支持 `POST`、注入 `Authorization: Bearer`、可注入 token 提供函数（保持现有 `getJson` 兼容与既有测试）。
* Pinia stores：`auth`（token 持久化 + `/me`）、`projects`、`workbench`（plan/run/events/tool-calls/artifacts）、`registry`。
* `types/` 下补齐契约类型；`router` 增加登录守卫（无 token 跳 `/login`）。
* 沿用现有暗色 Tailwind 设计语言（`surface-*`、`panel`、`kv`），复用 `StatePanel` 覆盖 loading/empty/error/permission。

### 3.2 页面
1. **登录页** `/login`：邮箱 + 口令 → 存 token → 跳工作台；错误用 `StatePanel` 区分 401/网络。
2. **工作台** `/workbench`（默认页）：
   - 选择可见项目 + 输入自然语言目标；
   - **预览计划**（`/runs/plan`）展示 intent / mode / steps（先给用户看「为什么这样做」）；
   - **执行**（`/runs`）→ Run 状态、Reviewer 结论、Task 列表；
   - **时间线**（`/events`）+ **工具调用**（`/tool-calls`）；
   - **Artifact 定制渲染**（按 `artifact_type`）：
     * `project_snapshot`：项目卡片；
     * `aftersales_diagnosis`：根因假设 / 置信度 / 证据 / 相似案例；
     * `quote_estimate`：推荐套餐 / 总价（¥）/ 明细 / 套餐对比 / 材料；
     * `design_proposal`：户型面积 / 空间规划 / 推荐风格（色板）/ 建议材料类目；
     * `construction_review`：进度阶段表（偏差/风险）/ 验收得分 / 缺陷 / 建议；
     * 兜底：原始 JSON。
3. **项目** `/projects`：列表（ACL）+ 详情抽屉/页（成员、客户、房屋）。
4. **注册中心** `/registry`：agents / skills / tools 三张只读表（风险等级、scope、允许工具）。
5. **审批**：Run 处于 `awaiting_approval` 时，在工作台内展示审批单 + approve/reject + resume（L2 技能才触发；seed 的 L0/L1 技能不触发，但契约完整可测）。

### 3.3 视觉
沿用现有暗色主题；新增少量 `@layer components`（如 `.btn`、`.input`、`.tag`）统一交互元素，不引入新的 UI 依赖。

---

## 4. 运行历史（待定，见确认问题）

后端**没有** `GET /runs` 列表端点。两种做法：
* **客户端本地记录（推荐）**：工作台把发起过的 Run id 记在 localStorage，历史列表点击后用 `GET /runs/{id}` 打开。零后端改动，纯前端。
* **新增后端端点**：`GET /api/v1/runs`（按 requester 收敛最近 N 条）+ `RunRepository.list_for_requester`。更真实（跨设备一致），但属后端改动。

---

## 5. Definition of Done

- [ ] `npm run typecheck`（vue-tsc --noEmit）零错误。
- [ ] `npm run test`（vitest）通过：新增 api / stores / 关键组件 / 路由守卫用例。
- [ ] `npm run build` 成功产出 `dist/`。
- [ ] 端到端可用（真实后端）：登录 → 选项目 → 预览计划 → 执行 → 时间线 → Artifact 定制渲染。
- [ ] 错误/空/权限三态均有展示（复用 `StatePanel`）。
- [ ] 文档更新（README 前端状态 + 新增 `docs/web-workbench.md`）+ Gate 报告。

---

## 6. 非目标（明确未做）

- 项目/成员/客户的写操作 UI（新建项目、加成员）——本阶段聚焦「看与用」，写操作后置。
- 实时流式（SSE）；本阶段用「执行后查询」而非订阅。
- 国际化、移动端深度适配、主题切换。
- 新增后端业务端点（除非运行历史选「新增端点」）。
- 可观测/评估、MCP、Kafka 主动式、Mem0（各自独立课题）。
