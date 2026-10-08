# MCP 传输层（apps/mcp-server）

> 对应需求文档「MCP | 标准化 Tool 调用」。本文描述**当前仓库中真实存在的代码**。

---

## 1. 目标

把 Agent Runtime 里**已注册且已启用**的工具（`ToolDefinition`）经 **MCP（Model Context Protocol）stdio 传输**
暴露给跨进程调用方；工具调用仍走完整治理链，**跨进程与 HTTP 入口的权限口径完全一致**。

---

## 2. 目录结构

```
apps/mcp-server/
  pyproject.toml          dw-mcp-server（console script: dw-mcp-server）
  src/dw_mcp_server/
    protocol.py           JSON-RPC 2.0 常量 / 响应构造 / 令牌提取（不碰 IO、不碰 DB）
    bridge.py             注册中心 ↔ MCP：列工具 + 经 ToolExecutor 调工具（含「MCP 会话 Run」）
    server.py             handle_message（解析→分发→序列化）+ serve（stdio 按行循环）
    __main__.py           入口：装配 Database / McpBridge，起 stdio 服务
```

---

## 3. 协议（MCP stdio 子集）

线格式：**每行一个 JSON 对象**（stdout 仅承载协议帧，日志一律走 stderr）。

| 方法 | 说明 |
|------|------|
| `initialize` | 返回 `protocolVersion` / `capabilities.tools` / `serverInfo` |
| `notifications/initialized` | 通知，无响应 |
| `ping` | 心跳 |
| `tools/list` | 列出已启用工具：`name` / `description` / `inputSchema`（由 Pydantic 入参模型导出） |
| `tools/call` | `params.name` + `params.arguments` → `result.content[].text` |

* **不引入 MCP Python SDK**：输运层只需按协议线格式收发；自实现零依赖、可离线单测。
  如需完整 SDK，只需替换 `server.py` 的传输循环，`bridge.py` / `protocol.py` 无需改动。
* 错误分层：**协议级错误**（解析失败 / 未知方法 / 参数非法 / 鉴权失败）走 JSON-RPC `error`；
  **工具执行错误**（未注册、缺 scope、入参校验失败）按 MCP 语义放在 `result` 里（`isError: true`）。

---

## 4. 鉴权与治理

1. 身份来源：`params._meta.authorization`（Bearer）优先，回退环境变量 `DW_MCP_TOKEN`；
2. 令牌用与 HTTP 同源密钥/算法校验（`dw_domain.security.decode_access_token`）；
3. 工具调用经 `ToolExecutor`：**scope → schema → 幂等 → 并发 → 超时 → 重试 → 降级 → 审计**；
4. 工具 handler 自身仍做 Project ACL（与 HTTP 一致）。

`tools/list` 只回元数据（schema），无需鉴权。

### 审计归属
MCP 没有 Run 概念。桥接层为**每个身份懒创建一个「MCP 会话 Run」**（`objective="MCP 会话"`），
所有 `tool_calls` / `audit_logs` 归属该 Run —— 不产生无主审计记录。

---

## 5. 运行与验证

```powershell
$env:DW_MCP_TOKEN = "<bearer-token>"   # 或用 params._meta.authorization 逐次传入
py -3 -m dw_mcp_server                  # 安装后： dw-mcp-server
```

一次调用（stdio）：

```jsonc
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"project_list","arguments":{"limit":5},"_meta":{"authorization":"Bearer <token>"}}}
```

已实测（子进程 stdio）：`serverInfo.name = dw-mcp-server`、`tools/list` 非空、缺令牌返回 `-32001`。

---

## 6. 非目标（本阶段未做）

* HTTP / SSE 传输（仅 stdio）。
* MCP 的 `resources` / `prompts` / `sampling` 等能力（只做 `tools`）。
* OAuth 等 MCP 授权流程（复用现有 JWT 校验）。
* 工具调用结果流式（一次性返回）。
