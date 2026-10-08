# dw-api

接入层（Controller）。**只做协议转换与横切逻辑，不承载业务逻辑**。

```
HTTP 请求
  ↓  RequestContextMiddleware   request_id / 访问日志 / 响应头
  ↓  SecurityHeadersMiddleware  安全响应头
  ↓  Router → Application Service（后续 Phase）→ Domain → Repository
  ↓  统一错误信封（ErrorEnvelope）
HTTP 响应
```

禁止：在这里写 SQL、在这里调 LLM、在这里堆业务规则（需求文档 §23）。

## Phase 0 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/live` | 存活探针，只要进程活着就 200 |
| GET | `/api/v1/ready` | 就绪探针，只探测**不可降级**依赖（PostgreSQL） |
| GET | `/api/v1/health` | 完整健康报告，含 Redis / Kafka 等可降级依赖状态 |

三者区别是有意为之：Redis 抖动不应该导致整个实例被摘掉，
但 PostgreSQL（业务事实源）不可用时必须返回 503。
