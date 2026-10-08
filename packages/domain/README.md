# dw-domain

领域层：**业务规则、持久化模型、应用服务**。这是唯一允许出现业务语义的包。

```
apps/api ──► packages/domain ──► packages/infrastructure ──► packages/schemas
```

| 模块 | 职责 |
|------|------|
| `models/` | SQLAlchemy ORM 模型 + 表约束（UUID PK / FK / 唯一约束 / 索引 / 乐观锁） |
| `repositories/` | 持久化读写，**只有查询语义，没有业务决策** |
| `services/` | 应用服务：事务边界 + 业务规则（如「建档自动成为 owner」） |
| `security.py` | 口令散列与 JWT 签发/校验（纯函数，便于单测） |
| `access_control.py` | RBAC + Project ACL 判定规则（纯函数，**可脱离 DB 单测**） |

## 组件引入说明

按需求文档 §25 的技术清单，Phase 1 只新增了一个第三方依赖：

| 组件 | `PyJWT` |
|------|---------|
| 为什么需要 | §13 要求 JWT 认证；手写 JWT 签名/验签容易在 alg 混淆、aud/exp 校验上出错 |
| 解决什么问题 | 标准化 HS256 令牌签发与过期校验 |
| 为什么已有组件不能解决 | stdlib 仅提供 HMAC，不提供令牌结构与 claim 校验 |
| 增加的运行成本 | 纯计算、无 IO、约 200KB |

口令散列**没有引入** argon2/passlib：
使用标准库 `hashlib.pbkdf2_hmac`（PBKDF2-HMAC-SHA256 + 每用户随机盐，600k 迭代），
既能满足当前安全基线又不增加密码学依赖；生产如需 argon2id，只需替换
`security.py` 中两个函数的实现，**调用方不变**。
