# dw-infrastructure

基础设施适配器层。**这是唯一允许出现 IO 与第三方 SDK 的共享包**。

职责边界：把「外部世界」翻译成上层可依赖的稳定接口（连接、探针、配置），
不包含任何业务规则，也不参与 Agent 编排（那是 `apps/agent-runtime` 的事）。

| 模块 | 内容 | 说明 |
|------|------|------|
| `config.py` | `Settings`（pydantic-settings） | 唯一配置入口；生产环境 fail-fast 校验 |
| `logging_setup.py` | 结构化 JSON 日志 + `request_id` 上下文 + 敏感字段脱敏 | §17 要求：禁止记录 API Key / 密码 |
| `db.py` | PostgreSQL 异步引擎与会话 | 业务事实源，含 pgvector 可用信息探测 |
| `redis.py` | Redis 客户端 | 短期运行状态，不做业务事实源 |
| `kafka.py` | Kafka Admin 连通性探测 | 业务事件总线（不做 Agent RPC） |
| `health.py` | 探针编排与系统状态聚合 | 支持 critical / 可降级依赖分级 |
