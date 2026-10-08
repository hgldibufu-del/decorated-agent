# 数据库说明（Database）

> 对应需求文档 §9、§22、报价估算（Phase 5）、设计提案（Phase 6）、施工审查（Phase 7）、长期记忆（Phase 10）。本文描述 **Phase 1 / Phase 4（RAG）/ Phase 5（报价）/ Phase 6（设计）/ Phase 7（施工）/ Phase 10（记忆）已落地的真实表结构**。

## 1. 基础事实

| 项 | 值 | 说明 |
|----|-----|------|
| 引擎 | PostgreSQL 16 + pgvector 0.8.x | pgvector 供 Phase 4 的 RAG 复用 |
| Schema | `workbench` | `ALTER DATABASE workbench SET search_path TO workbench, public` |
| 迁移工具 | Alembic（async + asyncpg） | 唯一建表途径，**禁止手工改表** |
| 主键 | UUID v4 | 避免自增 ID 泄露规模、便于跨环境合并 |
| 时间戳 | `timestamptz` | 统一 UTC，避免 asyncpg 拒绝写入 naive 列 |

`search_path` 由 `infra/postgres/init.sql` 设置。若 volume 已存在（脚本不会二次执行），
需要手工补一次：

```bash
docker exec dw-postgres psql -U decoration -d workbench \
  -c "ALTER DATABASE workbench SET search_path TO workbench, public;"
```

## 2. 表清单

### 身份与授权（§13）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `users` | `email`, `full_name`, `hashed_password`, `is_active`, `version` | `uq_users_email` |
| `roles` | `name`, `description` | `uq_roles_name` |
| `permissions` | `code`, `description` | `uq_permissions_code` |
| `user_roles` | `user_id`, `role_id` | 复合主键；两个 FK 均 CASCADE |
| `role_permissions` | `role_id`, `permission_id` | 复合主键；两个 FK 均 CASCADE |

角色与权限是**数据驱动**的：`ROLE_PERMISSIONS` 矩阵在
`packages/domain/src/dw_domain/rbac_defaults.py`，seed 与集成测试共用同一份定义。

### 项目域（§9）


| 表 | 关键列 | 约束 |
|----|--------|------|
| `customers` | `name`, `phone`, `email`, `note` | `uq_customers_phone` |
| `houses` | `customer_id`, `address`, `city`, `area_sqm`, `layout` | FK → `customers` **RESTRICT** |
| `projects` | `code`, `name`, `status`, `customer_id`, `house_id`, `budget_amount`, `version` | `uq_projects_code`；两个 FK **RESTRICT** |
| `project_members` | `project_id`, `user_id`, `role`, `joined_at` | `uq_project_members_project_id_user_id`；两个 FK **CASCADE** |

### Agent 基础设施（§6 / §8，Phase 2）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `agents` | `agent_id`, `agent_type`, `supported_skills`, `required_scopes`, `enabled` | `uq_agents_agent_id` |
| `skills` | `skill_id`, `agent_type`, `risk_level`, `allowed_tools` | `uq_skills_skill_id` |
| `tools` | `tool_id`, `timeout_ms`, `retry_max_attempts`, `fallback_tool_id`, `idempotency_required` | `uq_tools_tool_id` |
| `agent_runs` | `project_id`, `requester_id`, `status`, `mode`, `objective` | 两个 FK **RESTRICT** |
| `agent_tasks` | `run_id`, `task_key`, `agent_id`, `skill_id`, `risk_level`, `attempt` | `uq_agent_tasks_run_id_task_key`；FK CASCADE |
| `artifacts` | `run_id`, `artifact_type`, `producer`, `payload`, `version` | `uq_artifacts_run_id_type_version` |
| `tool_calls` | `run_id`, `tool_id`, `idempotency_key`, `status`, `duration_ms` | FK CASCADE |
| `approvals` | `run_id`, `task_id`, `status`, `decided_by`, `decided_at` | `decided_by` 用 **SET NULL** |
| `audit_logs` | `action`, `resource_type`, `resource_id`, `details`, `occurred_at` | 只追加，不更新 |

### RAG 证据底座（Phase 4，§8）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `rag_documents` | `title`, `source`, `metadata_json` | 文档级元数据 |
| `rag_document_chunks` | `document_id`, `seq`, `content`, `source`, `metadata_json`, `embedding vector(<dim>)` | `embedding` 走 pgvector；FK → `rag_documents` **CASCADE** |

* `embedding` 维度来自 `Settings.rag_embedding_dim`（默认 256），与迁移建表维度一致（单一事实源 = 配置）；
* 向量检索走 pgvector 的 `<=>` 余弦距离，BM25 走 `to_tsvector('simple', content)` + `ts_rank`；
* 索引：`ix_rag_document_chunks_embedding`（HNSW，`vector_cosine_ops`）+ `ix_rag_document_chunks_content_tsv`（GIN）；
* 维度可变：切换嵌入器（如 OpenAI 1536 维）须同步改 `Settings.rag_embedding_dim` 并重新生成迁移。

### 报价业务表（Phase 5，§5）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `quote_packages` | `name`, `tier`, `base_price`, `price_per_sqm`, `included_scope` | `uq_quote_packages_name` |
| `quote_items` | `category`, `name`, `unit`, `unit_price`, `metadata_json` | 工艺 / 材料项 |

* 报价为**业务表驱动的确定性计算**（与 AfterSales 的 RAG 证据路线并列，验证两种 Specialist 数据源都能挂进同一 Supervisor 编排骨架）；
* 金额统一 `NUMERIC(12,2)`，对外序列化为字符串（满足 §9 的金额约束，避免 float 舍入）；
* `budget_estimate` = 基础费 + 面积 × 单价；`package_compare` 在同一面积下对比多套餐；`material_lookup` 按类目 / 关键词检索工艺材料；
* `included_scope` / `metadata_json` 用 `JSONB`（真正动态的结构）。

### 设计业务表（Phase 6，§5）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `design_styles` | `name`, `style_family`, `suitable_layouts`, `palette`, `characteristics`, `tags` | `uq_design_styles_name` |
| `layout_modules` | `room_type`, `suggested_function`, `design_principle`, `recommended_material_category` | `uq_layout_modules_room_type` |

* 设计提案同为**业务表驱动的确定性合成**（不含 LLM），与 Quote 同构、与 AfterSales 的 RAG 路线并列；
* `layout_analysis` 从项目房屋的户型 + 面积推导空间规划建议；`style_match` 按偏好给风格打分排序；
* `suitable_layouts` / `palette` / `characteristics` / `tags` / `metadata_json` 用 `JSONB`（真正动态的结构）；
* 金额无关。

### 施工业务表（Phase 7，§5）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `construction_milestones` | `project_id`, `stage`, `seq`, `planned_days`, `actual_days`, `status` | `uq_construction_milestones_project_id_stage`；FK → `projects` **CASCADE** |
| `quality_checklists` | `category`, `item`, `standard`, `weight`, `severity` | `uq_quality_checklists_item` |

* 施工审查为**业务表驱动的确定性分析**（计划 vs 实际工期、验收项加权打分），可解释、可测、零外部依赖；
* `construction_milestones` 是**按项目**记录（沿用「项目域业务表」的 FK 策略：项目删除 → CASCADE），是 `progress_analysis` 的事实来源；
* `quality_checklists` 是全局验收项模板，供 `quality_check` 评估；
* 金额无关。

### 记忆层（Phase 10）

| 表 | 关键列 | 约束 |
|----|--------|------|
| `user_memories` | `user_id`, `kind`, `key`, `value`, `confidence`, `source`, `hits`, `last_used_at` | `uq_user_memories_user_id_kind_key`；FK → `users` **CASCADE** |

* 记忆是**按用户**的长期偏好（`preference` / `constraint` / `fact`），与项目无关，因此不参与 Project ACL —— 门禁只有 `memory:read` / `memory:write`；
* `(user_id, kind, key)` 唯一 → 同一偏好反复抽取也只留一行（幂等 upsert）；并发由约束兜底（数据库拒绝第二条，而非静默写出重复偏好）；
* `value` 用 `JSONB`：偏好形态多样（风格名 / 布尔标记 / 类目清单），强行收窄会逼出伪结构；
* `source` 记录来源（`run:<id>` / `manual`），可回答「为什么会记得」；
* **用户注销 → CASCADE 清除**，不留无法归属的偏好；金额无关。

## 3. 关键设计决策

| 决策 | 理由 |
|------|------|
| 客户/房屋外键用 `RESTRICT` | 它们是业务事实。误删客户不应把历史项目档案连坐抹掉 |
| 项目 → 成员用 `CASCADE` | 成员关系依附项目，项目删除时应一并清理 |
| 命名约定 `ix_/uq_/fk_/pk_` | 约束名可预期，迁移 diff 与代码评审都能读懂 |
| 乐观锁只在 `projects` / `users` | 只有会被并发修改的聚合根才需要；不是每张表都加 |
| 金额用 `NUMERIC(12,2)` | 报价金额走 float 会出现不可预测舍入误差 |
| role/permission 用 `String` 而非 PG enum | 枚举值由 Python 侧 `RoleName` / `PermissionCode` 保证；改枚举不需要迁移 |
| Agent 子表对 Run 用 `CASCADE` | Task / ToolCall / Artifact 依附 Run，Run 删除应连带清理 |
| `approvals.decided_by` 用 `SET NULL` | 审批人账号被删不应删掉审批记录（审计留痕不可被连坐） |
| `payload` / `details` 用 `JSONB` | 这些是**真正动态**的结构（Artifact 内容因技能而异）；业务字段仍用独立列 |
| 记忆按 `(user_id, kind, key)` 唯一 | 幂等来自**数据约束**而不是应用层判断，避免并发下写出重复偏好 |
| 记忆不做 Project ACL | 记忆没有项目维度；引入项目过滤只会让「用户的偏好」概念变糊 |

## 3.1 迁移历史

| 版本 | 内容 |
|------|------|
| `fe4c0e2d2682` | Phase 1 业务基线（users / roles / … / project_members） |
| `4d99a9011914` | Phase 2 Agent 基础设施（agents / skills / tools / runs / tasks / artifacts / tool_calls / approvals / audit_logs） |
| `19e26bb488f7` | Phase 3 Supervisor 计划与检查点（运行时不新增表，仅扩展 Run/Task 语义） |
| `4f1a2b3c5d6e` | Phase 3 Artifact 按 Task 收敛（扩展 artifacts 语义） |
| `5a1b2c3d4e5f` | Phase 4 RAG 证据底座（rag_documents / rag_document_chunks + pgvector 扩展） |
| `6b2c3d4e5f60` | Phase 5 报价业务表（quote_packages / quote_items） |
| `7c3d4e5f6071` | Phase 6 设计业务表（design_styles / layout_modules） |
| `8d4e5f607182` | Phase 7 施工业务表（construction_milestones / quality_checklists） |
| `9e5f60718293` | Phase 10 记忆层（user_memories） |

## 4. 迁移工作流

```powershell
./scripts/dev.ps1 migrate                 # alembic upgrade head
./scripts/dev.ps1 revision "add tickets"  # autogenerate 新迁移
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic current
```

* `alembic/env.py` 从 `dw_infrastructure.Settings` 读连接串，**不在 alembic.ini 重复配置**；
* `alembic.ini` 必须保持 ASCII（Alembic 用系统 locale 解码它，Windows GBK 会失败）；
* autogenerate 之后**必须人工复核**生成的脚本再提交。

## 5. 常用查询

```bash
# 列出业务表
docker exec dw-postgres psql -U decoration -d workbench \
  -tAc "select tablename from pg_tables where schemaname='workbench' order by 1;"

# 查看某项目的成员与角色
docker exec dw-postgres psql -U decoration -d workbench \
  -c "select p.code, u.email, m.role from project_members m
      join projects p on p.id=m.project_id
      join users u on u.id=m.user_id order by p.code;"
```
