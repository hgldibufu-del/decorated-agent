# 编辑与删除（完整 CRUD）Gate 报告

> 结论：**PASS**。项目 / 客户 / 房屋的编辑与删除闭环完成，含项目乐观锁。
> 日期：2026-10-05
> 范围：补齐写操作的编辑 / 删除；沿用既有 FK RESTRICT 策略（业务事实不被连坐删除）。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| 后端·领域 | `EntityInUseError`（外部引用冲突）；`SqlAlchemyRepository.delete_guarded`（FK RESTRICT → 领域异常） |
| 后端·仓储 | `ProjectRepository.save`（乐观锁，版本不符 → `StaleObjectError`）；`Customer/HouseRepository.save`；三类 `delete_guarded` |
| 后端·契约 | `ProjectUpdate`（含 `version`）、`CustomerUpdate`、`HouseUpdate`；`ProjectDetail` 增 `version` |
| 后端·服务 | `update_project`（can_write_project + 乐观锁）/ `delete_project`；`update/delete_customer`、`update/delete_house`（`project:write`） |
| 后端·路由 | `PUT/DELETE /projects/{id}`、`PUT/DELETE /customers/{id}`、`PUT/DELETE /houses/{id}` |
| 错误映射 | `StaleObjectError` / `EntityInUseError` → `ErrorCode.CONFLICT`（409） |
| 前端 | `ApiClient` 增 `putJson` / `delete`；`api` 与 stores 增 update/delete；`ReferenceManagePanel`（客户/房屋编删）；项目详情内「编辑（乐观锁）+ 删除」表单 |

---

## 2. 测试与质量

- **后端**：新增 `tests/integration/test_crud_api.py`（项目乐观锁成功 / 版本冲突 409 / 被 Run 引用删除 409 / 客户房屋 CRUD / 被引用删除 409 / 缺权限 403）；全量 **296 passed**（原 291，+5）。
- **前端**：`npm run typecheck` 零错误；`npm run test` **63 passed / 13 files**（原 56，+7：项目 update/delete、客户房屋 update/delete）；`npm run build` 成功。
- **`read_lints`**：零 error/warning。

---

## 3. Definition of Done 核对

- [x] 项目编辑带乐观锁：版本不符返回 409 CONFLICT，前端给出「已被他人修改」提示。
- [x] 项目 / 客户 / 房屋可删除；被下级引用时返回 409（与 FK RESTRICT 一致），前端有明确提示。
- [x] 权限：参考数据写操作要求 `project:write`；项目编辑/删除要求 `owner` / `manager`（或 admin）。
- [x] 后端新增端点集成测试全绿；前端 `typecheck` / `test` / `build` 全绿。
- [x] `read_lints` 零错误；文档更新（`README` 端点表 / `docs/web-workbench.md`）+ 本 Gate 报告。

---

## 4. 关键设计决策

1. **乐观锁只在项目上**：仅 `projects` 表带 `OptimisticLockMixin.version`（客户/房屋没有），因此乐观锁只对项目生效，客户/房屋为后写覆盖——不做无谓的迁移扩张。
2. **删除走 FK RESTRICT、不做级联**：业务事实（客户→房屋→项目→Run）不允许被连坐删除，删除被引用对象统一 409（`EntityInUseError`），保留历史。
3. **`version` 暴露到详情契约**：前端从 `GET /projects/{id}` 读 `version`，编辑时原样回传；契约新增字段向后兼容。
4. **前端入口按能力收敛**：`canWriteProjects`（全局 `project:write`）+ 项目内 `canManageProject`（owner/manager）双重判定，避免「点了就 403」的死路。
5. **复用既有错误码**：不新增 `ErrorCode`，`StaleObjectError` 与 `EntityInUseError` 均映射到既有 `CONFLICT`（409），符合「错误码注册表是唯一事实源」的约束。

---

## 5. 非目标（明确未做）

- 客户 / 房屋的「改挂客户」等结构调整（房屋不允许换客户）。
- 软删除 / 回收站（删除即终态；被引用则拒绝）。
- 批量操作、导入导出。
- 客户/房屋的乐观锁（表无 version 列）。

---

## 6. 下一步建议

- **真·实时**：worker 异步执行 + `GET /runs/{id}/stream`（SSE），替换非终态轮询。
- **软删除**：为项目引入 `archived` 状态，兼顾「保留历史」与「从列表移除」。
- 平台课题：Kafka 主动式、Mem0 记忆层、可观测与评估（Phase 9）、MCP 传输层。
