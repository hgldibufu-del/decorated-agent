# API 说明（API）

> 对应需求文档 §21。本文只收录**已实现**的端点，未实现的接口不会预先占位。

* Base Path：`/api/v1`
* 认证：`Authorization: Bearer <JWT>`（除 `/auth/login` 与健康探针外均需认证）
* OpenAPI：`GET /api/v1/openapi.json`、交互式文档 `/docs`
* 所有错误统一返回 `ErrorEnvelope`（见 §25）：`{code, message, request_id, retryable, category, details}`

## 1. 认证

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/auth/login` | 无 | `{email, password}` → `{access_token, token_type, expires_in}` |
| GET | `/auth/me` | JWT | 回查数据库返回最新角色/权限；账号停用后即使令牌未过期也返回 401 |

## 2. 项目

| 方法 | 路径 | 所需权限 | 说明 |
|------|------|----------|------|
| GET | `/projects` | JWT | 返回**当前用户可见**的项目（Project ACL 已收敛） |
| POST | `/projects` | `project:write` | 创建项目，创建者自动成为 `owner` |
| GET | `/projects/{project_id}` | 项目成员 + `project:read` | 返回客户、房屋与成员列表 |
| GET | `/projects/{project_id}/members` | 项目成员 + `project:read` | 成员列表 |
| POST | `/projects/{project_id}/members` | 成员角色 `owner`/`manager` + `project:write` | 新增成员；已存在则更新角色（幂等） |

## 2.1 注册中心（Phase 2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents` | Agent 注册中心（含 supported_skills / required_scopes） |
| GET | `/skills` | Skill 注册中心（含 risk_level / allowed_tools） |
| GET | `/tools` | Tool 注册中心（含 timeout / retry / fallback / 幂等策略） |

只读：注册中心的写入走 seed / 迁移，不开放 HTTP 写入 —— 否则「Supervisor 只能选合法 Agent」这条约束会被绕过。

## 2.2 Run / Artifact / Approval（Phase 2）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/runs` | Agent/Skill 的 required_scopes | Direct 模式发起一次 Run |
| GET | `/runs/{run_id}` | 发起人或 admin | Run 详情（含 Task 与 Artifact id） |
| GET | `/runs/{run_id}/events` | 同上 | 执行时间线（run / task / tool_call） |
| GET | `/runs/{run_id}/tool-calls` | 同上 | 工具调用明细（审计用） |
| GET | `/artifacts/{artifact_id}` | Run 发起人或 admin | Artifact 内容（§34 只传 id） |
| POST | `/approvals/{id}/approve` | `project:write` | 通过审批 |
| POST | `/approvals/{id}/reject` | `project:write` | 拒绝审批（Run 立即置 failed） |

工具错误映射：`TOOL_PERMISSION_DENIED` 403 / `TOOL_VALIDATION_ERROR` 400 /
`TOOL_CONFLICT` 409 / `TOOL_TIMEOUT` 504 / `TOOL_UNAVAILABLE` 503。

## 2.3 长期记忆（Phase 10）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/memories` | `memory:read` | 列出**当前用户**的长期记忆（按置信度 / 更新时间排序） |
| POST | `/memories` | `memory:write` | 写入或更新一条记忆；按 `(kind, key)` **幂等**（同键更新而非新增） |
| DELETE | `/memories/{key}` | `memory:write` | 删除当前用户指定 key 的记忆，返回实际删除条数 |

* **不接受 `user_id` 参数**：记忆是「当前用户自己的」，从令牌取身份即可 ——
  否则「改一个 id 就能读写别人的偏好」会成为一个越权面；
* 除 REST 外，记忆还会被 Run **自动写入**（执行后从 objective 抽取）与
  **自动读取**（执行前注入技能上下文）；且 `memory_recall` / `memory_remember`
  是走完整治理链的已注册工具，详见 [`memory.md`](./memory.md)。

## 3. 健康探针（无需认证，供编排系统使用）

| 方法 | 路径 | 语义 |
|------|------|------|
| GET | `/live` | 进程存活即 200 |
| GET | `/ready` | 只探测 PostgreSQL；失败 503 |
| GET | `/health` | 全量报告；Redis / Kafka 异常只降级（200） |

## 4. 鉴权判定口径

1. `admin` 角色对所有项目拥有读写权限，无需是成员；
2. 其他角色必须**先是项目成员**才谈得上权限；
3. 读：成员 + `project:read`；写：成员角色为 `owner`/`manager` + `project:write`；
4. 无权限一律返回 **403**（而不是 404）：项目 ID 是不可猜测的 UUID，
   403 不会泄露更多信息，却能让前端明确提示「无权限」。

规则实现在 `dw_domain.access_control`（纯函数），矩阵测试见 `tests/unit/test_access_control.py`。

## 5. 示例

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@dw.local","password":"Passw0rd!"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s http://127.0.0.1:8000/api/v1/projects -H "Authorization: Bearer $TOKEN"
```

发起一次 Run：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id":"supervisor_agent","skill_id":"project_snapshot",
       "objective":"加载项目上下文","project_id":"<uuid>","input":{"project_id":"<uuid>"}}'
# 201，status=completed，artifact_ids 非空；高风险技能返回 awaiting_approval 且 artifact_ids 为空
```

读写长期记忆：

```bash
# 写入（按 kind + key 幂等：再写同一个 key 是更新，不是新增）
curl -s -X POST http://127.0.0.1:8000/api/v1/memories \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"preference","key":"style","value":"新中式"}'

# 列出 / 删除
curl -s http://127.0.0.1:8000/api/v1/memories -H "Authorization: Bearer $TOKEN"
curl -s -X DELETE http://127.0.0.1:8000/api/v1/memories/style -H "Authorization: Bearer $TOKEN"
```

越权访问时的响应：

```json
{
  "code": "PERMISSION_DENIED",
  "message": "无权访问该项目",
  "request_id": "…",
  "retryable": false,
  "category": "permission_error",
  "details": {"error_type": "PermissionDeniedError"}
}
```
