# 前端工作台（apps/web）

> 对应需求文档 §19（界面状态）/ §21（接口）。本文描述**当前仓库中真实存在的前端代码**。

---

## 1. 目标与范围

把 `apps/web` 从「只有系统健康页的 Phase 0 骨架」补成可用工作台，让四个领域 Specialist
（AfterSales / Quote / Design / Construction）**端到端可见可用**：

登录 → 选项目 → 自然语言诉求 → 预览计划 → 执行 → 时间线 → Artifact 定制渲染。

技术栈不变：Vue 3 + TypeScript + Vite + Vue Router + Pinia + Tailwind，测试用 Vitest + @vue/test-utils。

---

## 2. 目录结构

```
apps/web/src/
  api/
    client.ts     统一错误信封解析（ApiError）+ Bearer 注入 + getJson/postJson
    session.ts    访问令牌存放（localStorage + 内存兜底，与框架解耦）
    auth.ts / projects.ts / registry.ts / runs.ts   后端端点封装
    history.ts    最近 Run 的本地记录（后端无 GET /runs 列表端点）
  types/          iam / project / agent / supervisor / artifact / health / ui 契约镜像
  stores/         auth / projects / registry / workbench（Pinia）
  components/
    StatePanel.vue / StatusBadge.vue（既有）
    PlanPreview.vue / RunTimeline.vue
    artifact/     ArtifactView 分发 + 五类定制渲染 + RawArtifact 兜底
  views/          LoginView / WorkbenchView / ProjectsView / RegistryView / HealthView
  router/         路由 + navigationGuard（纯函数）
```

---

## 3. 关键设计

### 3.1 令牌与鉴权
* 令牌存 `api/session.ts`（localStorage + 内存兜底），`ApiClient` 通过 `tokenProvider` 读取；
  **无令牌时不注入 `Authorization`**，保证既有健康检查请求头 byte 级不变（既有测试依赖此行为）。
* `router` 的 `navigationGuard` 是纯函数：未登录访问受保护页 → `/login?redirect=...`；已登录访问 `/login` → `/workbench`。

### 3.2 工作台流程
`WorkbenchView` 驱动 `workbench` store：
1. `preview()` → `POST /v1/runs/plan` 得到 `Plan`（先给用户看「为什么这样做」）；
2. `execute()` → 若未预览则自动补规划 → `POST /v1/runs`（带 `intent`）；
3. `hydrate()` 并发拉取 `GET /runs/{id}/events`、`/tool-calls`、各 `GET /artifacts/{id}`；
4. 历史：优先读后端 `GET /runs`（按 requester 收敛）；后端不可用时回退 `api/history.ts` 本地记录；
5. 实时：Run 非终态时每秒轮询 `GET /runs/{id}` + `/events`，终态自动停止（`startPolling` / `pollOnce`）。

### 3.5 写操作（客户 / 房屋 / 项目 / 成员）
* 后端补充最小参考数据端点：`GET/POST /customers`、`GET/POST /houses`、`GET /users`（均需 `project:write`）；
* 项目页按 `auth.canWriteProjects` 决定是否展示「新建客户 → 房屋 → 项目」面板与「添加成员」表单——
  无权限用户不展示入口，避免「点了就 403」的死路。

### 3.6 编辑与删除（完整 CRUD）
* **项目**：`PUT /projects/{id}` 携带乐观锁令牌 `version`（详情里读到、原样回传），版本不符 → `409 CONFLICT`，
  前端提示「已被他人修改，请重新打开后再改」；`DELETE /projects/{id}` 被 Run / 施工记录引用时同样 409。
* **客户 / 房屋**：`PUT/DELETE /customers/{id}`、`/houses/{id}`；被下级引用（客户→房屋、房屋→项目）时 409，
  与数据库 `RESTRICT` 策略一致——业务事实不被连坐删除。
* 客户 / 房屋的编辑删除入口收在 `ReferenceManagePanel`（选中 → 改 → 保存 / 删除）；
  项目编辑删除入口在项目详情内，仅对 `owner` / `manager`（或 admin）展示。

### 3.3 Artifact 定制渲染
`ArtifactView` 按 `artifact_type` 分发（后端各 SkillRunner 的 payload 形状见 `types/artifact.ts`）：

| artifact_type | 渲染要点 |
|---------------|----------|
| `project_snapshot` | 项目卡片（编号/客户/房屋/预算） |
| `aftersales_diagnosis` | 根因假设 / 置信度 / 处置建议 / 检索证据 / 相似案例 |
| `quote_estimate` | 推荐套餐 / 总价（¥）/ 费用明细 / 套餐对比 / 工艺材料 |
| `design_proposal` | 户型面积 / 推荐风格（色板）/ 空间规划 / 材料类目 |
| `construction_review` | 进度阶段表（偏差/风险）/ 验收得分 / 缺陷 / 建议 |
| 其它 | `RawArtifact` 原始 JSON 兜底 |

### 3.4 界面状态
复用既有 `StatePanel` 覆盖 `loading / empty / error / permission` 四态；`401/403` 单独走
「无权限」而不是「出错了」（二者用户动作不同）。

---

## 4. 本地运行

```powershell
# 1) 基础设施 + 建表 + 演示数据
docker compose up -d
./scripts/dev.ps1 migrate
./scripts/dev.ps1 seed

# 2) 后端
py -3 -m dw_api            # http://127.0.0.1:8000

# 3) 前端
cd apps/web
npm install
npm run dev                # http://localhost:5173（/api 代理到 127.0.0.1:8000）
```

演示账号（`scripts/seed.py`）：`pm.wang@dw.local` / `designer.zhao@dw.local` 等，口令 `Passw0rd!`。

校验命令：

```powershell
cd apps/web
npm run typecheck          # vue-tsc --noEmit
npm run test               # vitest run
npm run build              # vue-tsc + vite build
```

---

## 5. 非目标（本阶段未做）

* 项目 / 客户 / 房屋的**编辑与删除**（只做新建与查询）。
* 实时流式（SSE）；用「非终态轮询」，终态自动停止。
* 国际化、移动端深度适配、主题切换。
* 用户账号的创建与管理（仅提供成员候选查询）。
