# 工作台下半场 Gate 报告（写操作 UI + 实时时间线 + 运行历史后端化）

> 结论：**PASS**。
> 日期：2026-10-05
> 范围：补齐工作台的三个已知缺口；新增最小参考数据端点；运行历史后端化；非终态轮询。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| 后端·运行历史 | `RunRepository.list_for_requester` + `GET /api/v1/runs?limit=`（requester 收敛，admin 全量） |
| 后端·参考数据 | `GET/POST /customers`、`GET/POST /houses`、`GET /users`（`routes/reference.py`）+ 仓储 `list_all` + `ProjectService` 方法 + `UserBrief` 契约 |
| 前端·写操作 | `reference` store；`projects` store 增 `createProject` / `addMember`；项目页「新建客户 → 房屋 → 项目」面板 + 「添加成员」表单（按 `canWriteProjects` 收敛入口） |
| 前端·历史 | `workbench.loadRecent()` 优先读后端 `GET /runs`，失败回退本地记录 |
| 前端·实时 | `workbench` 增 `startPolling` / `stopPolling` / `pollOnce` + `isRunTerminal`；工作台展示「实时刷新中」 |
| 权限 | 参考数据端点统一要求 `project:write`（与 `POST /projects` 一致）；无权限入口不渲染 |

---

## 2. 测试与质量

- **后端**：新增 `tests/integration/test_reference_api.py`（客户/房屋建档、房屋需存在客户、成员候选、403）与 `tests/integration/test_runs_list.py`（requester 收敛 + limit）；全量 **291 passed**（原 285，+6）。
- **前端**：`npm run typecheck` 零错误；`npm run test` **56 passed / 13 files**（原 44，+12：reference / projects 写操作 / 轮询与历史）；`npm run build` 成功。
- **`read_lints`**：零 error/warning。

---

## 3. Definition of Done 核对

- [x] `GET /runs` 按 requester 收敛（admin 全量），前端历史来自后端、后端不可用时回退本地。
- [x] 可在 UI 完成「新建客户 → 新建房屋 → 新建项目」与「添加成员」闭环。
- [x] 时间线按所选方案（前端轮询）实现：非终态每秒刷新，终态自动停止。
- [x] 后端新增端点单测 + 集成测试全绿；前端 `typecheck` / `test` / `build` 全绿。
- [x] `read_lints` 零错误；文档更新（`README` 端点表 / `docs/web-workbench.md`）+ 本 Gate 报告。

---

## 4. 关键设计决策

1. **参考数据以 `project:write` 收敛**：客户/房屋/用户列表只服务于「建项目 / 加成员」，不对普通查看者开放；前端用 `auth.canWriteProjects` 决定是否渲染入口，避免死路。
2. **运行历史后端权威、本地兜底**：`GET /runs` 为权威来源；后端不可用时回退 `api/history.ts`（离线仍可用）。
3. **轮询而非 SSE**：Run 在 `POST /runs` 内同步执行，SSE 缺乏真实时间窗；且 `EventSource` 不能带 `Authorization` 头。轮询零后端流式改动、观感等价，终态自动停止避免空转。
4. **参考数据最小化**：只做客户/房屋的查询与创建、用户的候选查询，不做编辑/删除，不做账号管理。

---

## 5. 非目标（明确未做）

- 项目 / 客户 / 房屋的编辑与删除。
- 真·SSE 与后台执行（worker / Celery）。
- 用户账号的创建与管理。
- 国际化 / 移动端深度适配。

---

## 6. 下一步建议

- **真·实时**：引入 worker 异步执行 + `GET /runs/{id}/stream`（SSE），届时轮询可平滑替换为订阅。
- **编辑与删除**：项目/客户/房屋的完整 CRUD（含乐观锁冲突提示）。
- 平台课题：Kafka 主动式、Mem0 记忆层、可观测与评估（Phase 9）、MCP 传输层。
