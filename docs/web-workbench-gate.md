# 前端工作台 Gate 报告

> 结论：**PASS**。四个领域 Specialist 端到端可见可用。
> 日期：2026-10-05
> 范围：把 `apps/web` 从 Phase 0 骨架补成完整工作台；零后端业务改动（运行历史走客户端本地记录）。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| API 层 | `ApiClient` 扩展（Bearer 注入 + `postJson`）、`session.ts` 令牌存储、`auth/projects/registry/runs/history` 端点封装 |
| 契约镜像 | `types/`：iam / project / agent / supervisor / artifact / ui |
| 状态层 | Pinia stores：`auth` / `projects` / `registry` / `workbench` |
| 路由 | `router/index.ts` + 纯函数 `navigationGuard`（登录守卫 + redirect） |
| 页面 | 登录、AI 工作台、项目（列表 + 详情）、注册中心、系统健康（保留） |
| 组件 | `PlanPreview` / `RunTimeline` / `ArtifactView`（分发）+ 五类 Artifact 定制渲染 + `RawArtifact` 兜底 |
| 交互 | 预览计划 → 执行 → 时间线 / 工具调用 / Artifact；`awaiting_approval` 时 approve(+resume)/reject；本地运行历史 |

---

## 2. 测试与质量

- **类型检查**：`npm run typecheck`（vue-tsc --noEmit）零错误。
- **前端测试**：`npm run test`（vitest）**44 passed / 11 files**，含既有 17 个用例回归（client 6 / state-panel 7 / system 4）。
  新增：`session`、`auth-header`、`format`、`router/guard`、`stores/auth`、`stores/workbench`、`components/artifact-view`、`components/plan-preview`。
- **构建**：`npm run build` 成功（vue-tsc + vite build），产出 `dist/`（路由级懒加载分包）。
- **端到端（真实栈）**：后端 `py -3 -m dw_api`（health 200）+ 前端 `npm run dev`；经 Vite 代理
  `http://localhost:5173/api/v1/health` 返回 200，前后端连通。

---

## 3. Definition of Done 核对

- [x] `npm run typecheck` 零错误。
- [x] `npm run test` 通过（44 passed）。
- [x] `npm run build` 成功产出 `dist/`。
- [x] 端到端可用：登录 → 选项目 → 预览计划 → 执行 → 时间线 → Artifact 定制渲染（真实后端）。
- [x] 错误 / 空 / 权限三态均有展示（复用 `StatePanel`）。
- [x] 文档更新（`README` 相位表与测试计数 + 新增 `docs/web-workbench.md`）+ 本 Gate 报告。

---

## 4. 关键设计决策

1. **令牌与 client 解耦**：令牌放 `api/session.ts`，`ApiClient` 经 `tokenProvider` 读取；**无令牌不注入 Authorization**，既有健康检查请求头保持不变（既有测试断言了精确头部，故必须兼容）。
2. **纯函数守卫**：`navigationGuard` 抽成纯函数，便于单测且与 Vue Router 解耦。
3. **运行历史走本地**：后端无 `GET /runs` 列表端点，按确认结论用 localStorage 记录最近 Run id，打开时再 `GET /runs/{id}` 拉最新详情——零后端改动。
4. **Artifact 分发渲染**：`ArtifactView` 按 `artifact_type` 分发到五个专用组件，未知类型 `RawArtifact` 兜底，保证后端新增技能时前端不崩。
5. **复用既有设计语言**：沿用暗色 Tailwind（`surface-*` / `panel` / `kv`），仅新增 `.btn/.input/.tag/.th/.td` 少量组件类，未引入新 UI 依赖。

---

## 5. 非目标（明确未做）

- 项目 / 成员 / 客户的写操作 UI。
- 实时流式（SSE）。
- 国际化、移动端深度适配、主题切换。
- 新增后端业务端点。

---

## 6. 下一步建议

- **写操作 UI**：新建项目 / 加成员 / 发起审批决策的完整闭环。
- **实时时间线**：把 `/runs/{id}/events` 换成 SSE 订阅，边执行边刷新。
- **运行历史后端化**：新增 `GET /api/v1/runs`（按 requester 收敛），替换客户端本地记录。
- 其余平台课题：Kafka 主动式、Mem0 记忆层、可观测与评估（Phase 9）、MCP 传输层。
