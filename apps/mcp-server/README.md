# dw-mcp-server — MCP stdio 传输层

把 Agent Runtime 里**已注册且已启用**的工具（`ToolDefinition`）经 **MCP（Model Context Protocol）stdio 传输**
暴露给跨进程调用方。工具调用仍走 `ToolExecutor` 的完整治理链（scope → schema → 幂等 → 超时 → 重试 → 审计）。

> 设计取舍：不引入 MCP Python SDK，**自实现 JSON-RPC 2.0 协议子集**（`initialize` / `ping` / `tools/list` / `tools/call`）。
> 原因：本仓库对「工具契约与 MCP 对齐」的要求在 `ToolDefinition` 已满足，传输层只需按协议线格式读写；
> 自实现零第三方依赖、可离线单测，后续如需完整 SDK 只需替换 `server.py` 的传输循环。

## 运行

```powershell
# 需要一个访问令牌（JWT）作为调用身份；也可通过 DW_MCP_TOKEN 配置服务身份
$env:DW_MCP_TOKEN = "<bearer-token>"
py -3 -m dw_mcp_server          # 或安装后： dw-mcp-server
```

服务在 **stdin/stdout** 上按行收发 JSON-RPC（stdout 仅承载协议，日志一律走 stderr）。

## 支持的方法

| 方法 | 说明 |
|------|------|
| `initialize` | 返回 protocolVersion / capabilities / serverInfo |
| `ping` | 心跳 |
| `tools/list` | 列出已启用工具（name / description / inputSchema） |
| `tools/call` | 调用工具；`params.name` + `params.arguments` |

## 鉴权

`tools/call` 需要调用身份：

1. 优先取 `params._meta.authorization`（形如 `Bearer <token>`）；
2. 否则回退到环境变量 `DW_MCP_TOKEN`。

令牌用与 HTTP 接入层相同的密钥 / 算法校验，解析出 `UserIdentity` 后由 `ToolExecutor` 做 scope 校验，
工具 handler 自身再做 Project ACL —— **跨进程与 HTTP 入口的权限口径完全一致**。

`tools/list` 只回元数据（schema），无需鉴权。

## 一次调用示例（stdio）

```jsonc
// 客户端 → 服务
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"project_list","arguments":{"limit":5},"_meta":{"authorization":"Bearer <token>"}}}
```
