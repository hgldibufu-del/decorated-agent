# 装修企业 AI Agent Workbench

> **Codex 式装修领域 AI Agent 平台**
>
> 用户只有一个自然语言入口；Supervisor 负责理解任务并生成执行 DAG，动态调度
> Design / Quote / Construction / AfterSales 等 Specialist Agent；Specialist 通过 Skill
> 调用受治理的 MCP Tools；LangGraph 负责编排与 Checkpoint，Kafka 负责业务事件，
> PostgreSQL 负责业务事实，RAG 负责知识证据，Reviewer 负责质量门控。

本仓库按 **Phase 分批交付**（需求文档 §29）。当前状态：**Phase 0-7 已完成**（四个领域 Specialist 全部落地），**前端工作台（apps/web）已补齐**，**Phase 9 可观测与评估（OpenTelemetry 追踪 + 确定性检索评估）已落地**，**Phase 10 记忆层（长期偏好）已落地**。

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 0 | Monorepo、Docker Compose、PostgreSQL(pgvector) / Redis / Kafka、FastAPI、Vue 3、配置 / 日志 / 健康检查、lint / format / test、CI | ✅ 已完成 |
| Phase 1 | User / Role / Permission / Project / ProjectMember / Customer / House、JWT / RBAC / Project ACL、Alembic 迁移、Seed | ✅ 已完成 |
| Phase 2 | Agent / Skill / Tool 注册中心、Tool 治理链、Run/Task/Artifact/Approval | ✅ 已完成 |
| Phase 3 | Supervisor / Planner / DAG / Reviewer / Checkpoint | ✅ 已完成 |
| Phase 4 | RAG 证据底座（pgvector + BM25 + RRF）+ AfterSales Specialist | ✅ 已完成 |
| Phase 5 | Quote Specialist（业务表驱动的报价估算） | ✅ 已完成 |
| Phase 6 | Design Specialist（设计提案） | ✅ 已完成 |
| Phase 7 | Construction Specialist（施工审查） | ✅ 已完成 |
| 前端工作台 | 登录 / 项目 / AI 工作台 / 注册中心（apps/web） | ✅ 已完成 |
| Phase 9 | Observability（OpenTelemetry 追踪 + 确定性检索评估；Langfuse / RAGAS 留协议接缝） | ✅ 已完成 |
| Phase 10 | Memory（长期偏好：确定性记忆层 + 受治理记忆工具；mem0ai 留协议接缝） | ✅ 已完成 |

---

## 1. 系统架构

```
用户 ──► Supervisor Agent ──► Planner ──► Execution DAG ──► Specialist Agents
                                                              │
                                                        Skill Registry
                                                              │
                                                        MCP Tool Runtime
                                                              │
                              ┌───────────────┬───────────────┼──────────────┐
                              ▼               ▼               ▼              ▼
                         PostgreSQL       RAG(pgvector)     Redis          Kafka
                         业务事实          知识证据        短期运行状态     业务事件
```

已落地的部分：**底座（Phase 0）** + **业务地基（Phase 1）**。
Agent 编排与 Supervisor 尚未引入，但分层已经固定，
后续 Phase 只往对应目录追加代码，不再做结构性返工。

详细的职责边界与目录分工见 [`docs/architecture.md`](./docs/architecture.md)。

### 1.1 Monorepo 布局

```
apps/
  api/         FastAPI 接入层（Phase 0）
  web/         Vue 3 + TypeScript 工作台前端（Phase 0）
  agent-runtime/  注册中心 + 工具治理 + Run 执行（Phase 2）
  worker/         Celery 异步任务（Phase 3+）
  mcp-server/     MCP stdio 传输层（已实现，零第三方依赖）
packages/
  schemas/        跨 app / package 共享的 Pydantic 契约
  infrastructure/ 配置 / 日志 / DB / Redis / Kafka 适配器
  domain/         领域模型 / 仓储 / 应用服务 / 鉴权策略（Phase 1）
  ui/             共享前端组件（Phase 8）
infra/
  postgres/       数据库初始化脚本
scripts/
  dev.ps1         本地任务运行器（Windows）
```

每个 `apps/*` 与 `packages/*` 都是**独立的 Python 分发包**，拥有自己的 `pyproject.toml`。
`dw-api` 依赖 `dw-infrastructure`，后者依赖 `dw-schemas`；这些本地依赖由 pip 在同一次
解析中从本地路径满足（见 `requirements-dev.txt`）。

> 说明：`packages/ui`、`apps/worker` 尚未创建。
> 在还没有真实代码时不预先建空包 —— 空包会被误读为“已实现”。

---

## 2. 技术栈

| 层 | 选型 | 本阶段是否启用 |
|----|------|----------------|
| Backend | Python 3.10+、FastAPI、Pydantic、SQLAlchemy 2.0、uvicorn | ✅ |
| Frontend | Vue 3、TypeScript、Vite、Vue Router、Pinia、Tailwind CSS | ✅ |
| Data | PostgreSQL 16 + pgvector、Redis 7 | ✅ |
| Event | Kafka 3.9（KRaft 单节点） | ✅（仅连通性与幂等建 topic） |
| Agent | LangGraph、PydanticAI、MCP | ⏳ Phase 2+ |
| RAG | pgvector + BM25 + Reranker | ⏳ Phase 4+ |
| Observability | OpenTelemetry（链路追踪）、自研确定性检索评估 | ✅（Langfuse / RAGAS 留接缝） |
| Quality | ruff（lint+format）、mypy、pytest、vitest、vue-tsc | ✅ |

---

## 3. 环境变量

复制模板后按需修改：

```bash
cp .env.example .env
```

关键变量（完整清单见 [`.env.example`](./.env.example)）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_ENV` | `development` | `development` / `testing` / `production` |
| `APP_DEBUG` | `true` | 生产环境必须为 `false`，否则启动即失败 |
| `SECRET_KEY` | 开发占位串 | 生产环境要求长度 ≥ 32 且非默认值，否则启动即失败 |
| `JWT_ALGORITHM` | `HS256` | 仅支持 HS256（算法白名单，防 alg=none 攻击） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | 权限写在令牌里，撤销不即时生效，故不宜过长 |
| `DEFAULT_SEED_PASSWORD` | `Passw0rd!` | 种子用户统一口令；使用默认值时 seed 会打印警告 |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 生产环境禁止 `*`，否则启动即失败 |
| `POSTGRES_*` | `localhost` / `55432` / `decoration` / `decoration` / `workbench` | 见下方端口说明 |
| `DATABASE_URL` | 空 | 显式覆盖时使用，优先级高于上面字段拼装 |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9094` | 容器内访问请用 `kafka:9092` |
| `HEALTH_PROBE_TIMEOUT_MS` | `3000` | 单探针超时 |
| `MOCK_LLM` | `true` | Phase 3+ 生效；`true` 时不依赖任何真实 API Key |
| `OTEL_ENABLED` | `false` | Phase 9；关闭时全部 span 为 no-op，行为与接入前一致 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | Phase 9；配置后才真正导出（需装 extras `dw-infrastructure[otel]`） |
| `OTEL_SERVICE_NAME` | 空 | Phase 9；留空回落到 `SERVICE_NAME` |
| `OTEL_TRACE_SAMPLE_RATIO` | `1.0` | Phase 9；< 1 时按 ParentBased + TraceIdRatio 采样 |

> **为什么 Postgres 宿主机端口是 55432？**
> 本机通常已经装有 Windows 版 PostgreSQL 并占用 5432；容器再映射 5432 会出现
> 两个进程同时监听、连接被随机路由到错误实例的情况（表现为连接重置）。
> 容器内端口仍然是 5432。

安全约定：任何密钥都只能经由环境变量注入，**不得写死在源码**；`SECRET_KEY` 等校验在
`packages/infrastructure/src/dw_infrastructure/config.py` 中做 fail-fast。

---

## 4. 启动方式

### 4.1 前置条件

* Python ≥ 3.10（本机使用 `py` 启动器，Python 3.10.11）
* Node ≥ 20（本机 Node 24）
* Docker + Docker Compose

### 4.2 一键启动基础设施

```bash
docker compose up -d          # Postgres(pgvector) / Redis / Kafka
docker compose ps             # 三个容器应均为 healthy
```

PostgreSQL 首次创建 volume 时会执行 `infra/postgres/init.sql`：
安装 `vector` / `pgcrypto` / `pg_trgm` 扩展并创建 `workbench` schema。

### 4.3 后端

```powershell
py -m venv .venv                                   # Windows
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m dw_api               # 或 scripts/dev.ps1 api
```

Linux / macOS 等价：

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m dw_api
```

服务起来后：

| 端点 | 说明 |
|------|------|
| `GET /api/v1/live` | 存活探针，进程活着即 200 |
| `GET /api/v1/ready` | 就绪探针，**只探测不可降级依赖**（PostgreSQL） |
| `GET /api/v1/health` | 完整健康报告，含 Redis / Kafka 等可降级依赖 |
| `POST /api/v1/auth/login` | 登录换取 JWT |
| `GET /api/v1/auth/me` | 当前用户与角色权限（回查数据库） |
| `GET/POST /api/v1/projects`、`PUT/DELETE /api/v1/projects/{id}` | 项目列表 / 新建 / 编辑（乐观锁）/ 删除 |
| `GET /api/v1/projects/{id}`、`/members` | 项目详情与成员 |
| `POST /api/v1/projects/{id}/members` | 新增或更新成员（幂等） |
| `GET/POST/PUT/DELETE .../customers`、`.../houses` | 客户 / 房屋的增删改查（需 `project:write`） |
| `GET /api/v1/users` | 成员候选用户（需 `project:write`） |
| `GET/POST /api/v1/runs`、`GET /api/v1/runs/{id}` `/events` `/tool-calls` | 发起 / 列出 Run、时间线、工具调用明细 |
| `GET /api/v1/artifacts/{id}` | 读取 Artifact |
| `GET/POST/DELETE /api/v1/memories` | 长期记忆（需 `memory:read` / `memory:write`） |
| `GET /api/v1/agents`、`/skills`、`/tools` | 注册中心（只读） |
| `GET /api/v1/openapi.json`、`/docs` | OpenAPI 文档 |

完整接口说明见 [`docs/api.md`](./docs/api.md)。

三者刻意区分：Redis 抖动只应让系统降级，不应把实例从负载均衡摘掉；
PostgreSQL 不可用时必须返回 503。

### 4.4 前端

```powershell
cd apps/web
npm install
npm run dev        # http://localhost:5173
```

dev server 已配置 `/api` 代理到 `http://127.0.0.1:8000`，因此前端始终用相对路径请求。

### 4.5 用任务运行器

本机没有 `make`，统一使用 PowerShell 运行器（所有命令均已实际验证）：

```powershell
./scripts/dev.ps1 help        # 查看全部任务
./scripts/dev.ps1 bootstrap   # 建 venv + 装依赖
./scripts/dev.ps1 up          # 起基础设施
./scripts/dev.ps1 check       # lint + typecheck + test
./scripts/dev.ps1 fe-build    # 前端构建
```

---

## 5. 数据库初始化

`infra/postgres/init.sql` 只负责扩展（`vector` / `pgcrypto` / `pg_trgm`）、`workbench`
schema 与 `search_path`。**建表一律走 Alembic 迁移**，不要手工改表：

```powershell
./scripts/dev.ps1 migrate                 # alembic upgrade head
./scripts/dev.ps1 revision "add tickets"  # 自动生成新迁移（生成后必须人工复核）
.\.venv\Scripts\python.exe -m alembic current
```

表结构、外键删除策略与约束清单见 [`docs/database.md`](./docs/database.md)。

验证数据库就绪：

```bash
curl -s http://127.0.0.1:8000/api/v1/health
# components[postgres].metadata.pgvector 应为版本号而非 "not-installed"
```

---

## 6. Seed 数据

```powershell
./scripts/dev.ps1 seed        # 等价于 python scripts/seed.py
```

幂等：用户按邮箱、客户按手机号、房屋按地址、项目按编号去重，可反复执行。

| 数据 | 数量 |
|------|------|
| 角色 / 权限 | 7 / 11（矩阵见 `packages/domain/src/dw_domain/rbac_defaults.py`） |
| 用户 | 10（`admin@dw.local` … `viewer.hu@dw.local`） |
| 客户 / 房屋 / 项目 | 5 / 5 / 5 |
| 项目成员 | 13 |
| Agent / Skill / Tool | 5 / 5 / 15（只注册已有真实执行体的能力：Supervisor + 四个领域 Specialist + 记忆工具） |

默认口令 `Passw0rd!`，可用 `DEFAULT_SEED_PASSWORD` 覆盖；使用默认值时脚本会打印警告。
**材料 / 工单 / 业务事件 / 知识文档**属于后续 Phase，本阶段不提供占位数据。

---

## 7. 测试

后端：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy apps packages
```

前端：

```powershell
cd apps/web
npm run typecheck
npm test
npm run build
```

说明：

* **跑测试前先建表**：集成测试依赖业务表，需先 `./scripts/dev.ps1 migrate`。
* **集成测试默认必须执行**。中间件不可达时应当失败，而不是静默跳过；
  只有在确实没有基础设施的流水线里才设置 `SKIP_INTEGRATION=1` 显式跳过。
* 集成测试覆盖真实 PostgreSQL（含事务回滚、登录、Project ACL 越权）、
  Redis（含 TTL）、Kafka（含幂等建 topic）。
* ACL 的数据由测试自己创建并登记清理，不依赖 seed，避免测试顺序影响结果。
* 与这些测试同一套 `docker compose` 配置，避免 CI 与本地环境漂移。
* **检索质量有回归闸门**：`tests/integration/test_observability.py` 用内置 golden set
  断言 hit@3 / recall@3 / MRR 不低于阈值（确定性，可离线复现）。
* **评估可单独运行**（输出 JSON 汇总 + 逐案明细）：

  ```powershell
  .\.venv\Scripts\python.exe -m dw_infrastructure.evaluation
  ```

  追踪与评估的设计取舍见 [`docs/observability.md`](./docs/observability.md)。
* **长期偏好有独立测试**：`tests/integration/test_memory.py` 覆盖幂等往返、自动抽取、
  「记忆影响设计提案」与「无权用户不受影响」；设计取舍见 [`docs/memory.md`](./docs/memory.md)。

---

## 8. Demo 流程

```powershell
./scripts/dev.ps1 bootstrap
./scripts/dev.ps1 up
./scripts/dev.ps1 migrate                   # 建业务表
./scripts/dev.ps1 seed                      # 灌演示数据
.\.venv\Scripts\python.exe -m pytest -q     # 348 passed（后端）
.\.venv\Scripts\python.exe -m dw_api        # 另开终端
curl.exe -s http://127.0.0.1:8000/api/v1/health
```

预期输出（真实采自本机）：

```json
{
  "status": "healthy",
  "service": "dw-api",
  "version": "0.1.0",
  "environment": "development",
  "components": [
    {"name": "postgres", "status": "healthy", "critical": true,  "latency_ms": 127.51,
     "metadata": {"server_version": "16.15", "pgvector": "0.8.7"}},
    {"name": "redis",    "status": "healthy", "critical": false, "latency_ms": 114.43,
     "metadata": {"redis_version": "7.4.11", "connected_clients": 1}},
    {"name": "kafka",    "status": "healthy", "critical": false, "latency_ms": 114.95,
     "metadata": {"topic_count": 1}}
  ]
}
```

演示降级与不可用：

```powershell
docker compose stop redis
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/api/v1/health   # 200，status=degraded

docker compose stop postgres
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/api/v1/ready    # 503，status=unhealthy
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/api/v1/live     # 200，进程仍存活

docker compose start redis postgres
```

### 8.2 登录与 Project ACL（本机实测结果）

```powershell
# 管理员：可见全部 5 个项目，member_role 为 null（不是成员）
# 售后吴倩：只见 GC-2026-005；只读胡静：只见 GC-2026-003
# 越权访问他人项目 → 403 PERMISSION_DENIED
# 预算员孙博（有 project:read，无 project:write）创建项目 → 403
# 项目经理创建项目 → 201，创建者自动成为 owner，budget=123456.78 精度无损
```

账号与口令见 `scripts/seed.py` 的 `USERS`（默认口令 `Passw0rd!`）。

### 8.3 Agent Run（本机实测结果）

```powershell
# GET /api/v1/agents → supervisor_agent（支持 project_snapshot）
# GET /api/v1/skills → project_snapshot（L0，允许 project_query / artifact_query）
# GET /api/v1/tools  → project_query / project_list / artifact_query

# POST /api/v1/runs → 201 completed，1 个 Task、1 个 Artifact
# GET /api/v1/artifacts/{id} → payload.project.code = GC-2026-001
# GET /api/v1/runs/{id}/events → run | task | tool_call 时间线
# GET /api/v1/runs/{id}/tool-calls → project_query success attempt=1 22ms
# audit_logs：tool_call + run_completed 各 1 条

# 风险等级 L2 的技能 → 201 awaiting_approval，approval_id 非空，artifact_ids 为空
# POST /approvals/{id}/reject → approval rejected，Run 立即 failed
```

详见 [`docs/agent-runtime.md`](./docs/agent-runtime.md)。

---

## 9. 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `UnicodeDecodeError: 'gbk' codec` 安装依赖失败 | pip 用系统 locale 解码 requirements 文件 | 这两个文件必须保持 ASCII（已在文件头注明）；其他文件不要被 pip 读取 |
| pg 报 `connection was closed in the middle of operation` | 本机 Windows PostgreSQL 占用了 5432 | 用 55432；`netstat -ano \| Select-String ":5432"` 确认是否有多进程监听 |
| `/health` 中 kafka 一直 unhealthy | 宿主机应连 `localhost:9094`，容器内才是 `9092` | 修改 `KAFKA_BOOTSTRAP_SERVERS` |
| `docker compose up` 后 schema / 扩展没建出来 | volume 已存在，`init.sql` 只在首次创建时执行 | `docker compose down -v` 重建，或手工执行 `infra/postgres/init.sql` |
| 集成测试大面积失败 | 基础设施没起起来（不是代码问题） | `docker compose ps` 确认三个容器均为 healthy |
| 前端请求 404 / 502 | dev server 代理未连到后端 | 确认后端在 127.0.0.1:8000 且已启动 |
| 生产启动报 `生产环境配置不安全` | fail-fast 校验命中（密钥过短 / CORS 通配 / DEBUG 未关） | 按提示修正环境变量，不要绕过校验 |
| `relation "users" does not exist` | 没跑迁移，或 `search_path` 未指向 `workbench` | `./scripts/dev.ps1 migrate`；确认 `SHOW search_path` 返回 `workbench, public` |
| `UnicodeDecodeError: 'gbk' codec` 跑 alembic 失败 | Alembic 用系统 locale 读 `alembic.ini` | 该文件必须保持 ASCII（已在文件头注明） |
| `MissingGreenlet` 异常 | async 会话里访问了未加载的关系属性 | 用 `lazy="selectin"`，或写入后重新按 eager-load 查询；不要给集合直接赋值 |
| 迁移生成了空脚本 | ORM 模型没被 import 进 metadata | `alembic/env.py` 必须 `from dw_domain.models import Base` |
| 端口 8000 已被占用（`Errno 10048`） | 旧进程未退出（本仓库早期用系统 Python 起过服务） | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object { $_.CommandLine -match "dw_api" }` 定位后停掉 |
| `POST /runs` 返回 `awaiting_approval` 却拿不到结果 | 该技能风险等级 ≥ L2，需人工审批 | 这是设计行为；审批后恢复执行属 Phase 3 |

---

## 10. 许可证

MIT
