# MCP 传输层 Gate 报告

> 结论：**PASS**。`apps/mcp-server` 把已注册工具经 MCP stdio 暴露，调用走完整治理链。
> 日期：2026-10-05
> 范围：MCP stdio 传输层（零第三方依赖）；三个平台课题的第 1 个（MCP → 可观测 → Mem0）。

---

## 1. 本次交付

| 类别 | 交付 |
|------|------|
| 新 app | `apps/mcp-server`（包 `dw_mcp_server`，console script `dw-mcp-server`；依赖 dw-agent-runtime / dw-domain / dw-infrastructure / dw-schemas） |
| 协议 | `protocol.py`：JSON-RPC 2.0 常量 / 响应构造 / `initialize_result` / 令牌提取，**不碰 IO 与 DB** |
| 桥接 | `bridge.py`：`list_tools`（注册中心 × ToolDefinition → MCP 描述）；`call_tool`（经 `ToolExecutor`）；「MCP 会话 Run」承载审计 |
| 服务 | `server.py`：`handle_message`（解析→分发→序列化）+ `serve`（stdio 按行循环）；`__main__.py` 入口 |
| 工程 | root `pyproject.toml` pythonpath + `requirements-dev.txt` 纳入新包；`py.typed` |

---

## 2. 测试与质量

- **单元**：`tests/unit/test_mcp_protocol.py`（10 例）：initialize / ping / 通知无响应 / 未知方法 -32601 / 解析错误 -32700 / 缺 name -32602 / 缺令牌 -32001 / Bearer 提取 / 工具描述含 inputSchema。
- **集成**：`tests/integration/test_mcp_server.py`（4 例，真实 PG）：`tools/list` 元数据、`tools/call project_list` 成功且**审计归属到「MCP 会话 Run」**、缺 scope 被治理链拒绝（in-band isError）、未注册工具报错。
- **全量**：后端 **310 passed**（原 296，+14）；`read_lints` 零 error/warning。
- **线格式实测**：以子进程方式启动 `py -3 -m dw_mcp_server`，stdio 收发 `initialize` / `tools/list` / 无令牌 `tools/call`，结果 `SERVER_NAME=dw-mcp-server`、`TOOLS_NONEMPTY=YES`、`UNAUTHORIZED_CODE=-32001`。

---

## 3. Definition of Done 核对

- [x] `apps/mcp-server` 可独立启动（stdio），暴露已注册工具。
- [x] `tools/list` 返回 name / description / inputSchema（来自 Pydantic 入参模型）。
- [x] `tools/call` 经 `ToolExecutor`（scope/schema/幂等/超时/重试/审计），权限口径与 HTTP 一致。
- [x] 审计可归属（「MCP 会话 Run」），无无主记录。
- [x] 单元 + 集成全绿；`read_lints` 零错误；文档更新（README / architecture / agent-runtime + 本报告）。

---

## 4. 关键设计决策

1. **自实现协议子集、不引入 SDK**：工具契约已在 `ToolDefinition` 满足，传输层只需线格式；零依赖、可离线单测，未来可平滑替换为完整 SDK。
2. **错误分层**：协议级错误走 JSON-RPC `error`；工具执行错误按 MCP 语义 in-band（`isError`），客户端可区分「调用没打通」与「调用打通但业务失败」。
3. **审计归属**：MCP 无 Run，为每个身份懒创建一个「MCP 会话 Run」，让治理链的 `tool_calls` / `audit_logs` 有归属。
4. **鉴权同源**：复用 HTTP 的 JWT 校验与 `ToolExecutor` 的 scope 检查，杜绝「跨进程绕过权限」。
5. **stdout 只写协议**：入口刻意不调用写 stdout 的日志配置，保证协议流不被污染。

---

## 5. 非目标（明确未做）

- HTTP / SSE 传输；MCP `resources` / `prompts` / `sampling`；OAuth 授权流程；结果流式。

---

## 6. 下一步（本课题序列）

**可观测与评估（Phase 9）**：接入 OpenTelemetry 链路追踪（Run/Task/Tool 调用打 span）+ 评估（Langfuse / RAGAS）——
把当前「日志 + 审计表」的观测能力升级为可查询的 trace 与可量化的评估。之后再做 **Mem0 记忆层**。
