# dw-agent-runtime

Agent 基础设施：**注册中心 + 工具治理 + Run 执行**。

```
apps/api ──► apps/agent-runtime ──► packages/domain ──► packages/infrastructure
               注册中心 / 治理链 / RunService
```

| 模块 | 职责 |
|------|------|
| `registry.py` | Agent / Skill / Tool 三大注册中心：从 DB 加载为不可变 Spec，并做一致性校验 |
| `tools.py` | 内置工具定义（Pydantic 入参既做校验又生成 JSON Schema） |
| `executor.py` | `ToolExecutor`：§12 要求的完整治理链 |
| `skills.py` | 技能执行体（Phase 2 只实现了 `project_snapshot`） |
| `runs.py` | `RunService`：Direct 模式建 Run/Task、风险审批门控、产出 Artifact |

## 治理链（需求文档 §12）

```
权限校验 → 入参校验 → 幂等检查 → 并发控制 → 超时 → 重试 → 降级 → 审计
permission  schema   idempotency  semaphore  timeout  retry  fallback  audit
```

每一环都有对应的领域异常与单测：

| 环节 | 异常 | HTTP |
|------|------|------|
| 权限 | `ToolPermissionError` | 403 |
| 入参 | `ToolValidationError` | 400 |
| 幂等冲突 | `ToolConflictError` | 409 |
| 超时 | `ToolTimeoutError` | 504（可重试） |
| 未注册 / 未实现 | `ToolUnavailableError` | 503（可重试） |

## 关于 MCP

本阶段交付的是 **Tool Runtime**：工具以 `ToolDefinition(handler, input_model)` 形式注册，
对外契约（工具清单、入参/出参 JSON Schema、`tools/call` 语义）与 MCP 对齐，
但尚未落地 stdio/HTTP 的 MCP 传输层。原因：Phase 2 还没有跨进程调用方，
提前引入传输层属于「为炫技增加技术」（规则 5）。Phase 3 Supervisor 需要跨进程
调度外部工具时再补传输层，`ToolDefinition` 无需改动。
