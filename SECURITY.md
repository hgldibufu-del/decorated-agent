# 安全策略（Security Policy）

## 支持版本

| 版本 | 支持 |
|------|------|
| 0.x（Phase 0） | ✅ 仅本仓库当前代码 |

## 报告漏洞

请勿通过公开 Issue 报告安全问题。请发送邮件至 `security@example.com`，
并在其中包含：复现步骤、影响范围、可能的修复建议。

---

## Phase 0 已落实的安全能力

| 能力 | 落点 | 状态 |
|------|------|------|
| 密钥仅经环境变量注入，禁止硬编码 | `dw_infrastructure/config.py`（`Settings`） | ✅ 已实现 |
| 生产环境 fail-fast 校验 | `Settings._validate_production_safety` | ✅ 已实现 |
| 日志敏感字段脱敏（Key / Secret / Token / 密码） | `dw_infrastructure/logging_setup.py` | ✅ 已实现 |
| 安全响应头 | `dw_api/middleware.py`（`SecurityHeadersMiddleware`） | ✅ 已实现 |
| CORS 白名单（`*` 在生产被拒绝） | `dw_api/app.py` + `Settings` | ✅ 已实现 |
| 错误信息不泄漏内部细节 | `dw_api/errors.py`（500 统一信封，`logger.exception` 记全栈） | ✅ 已实现 |
| request_id 全链路可追溯 | 中间件 + 日志 + 错误信封 | ✅ 已实现 |
| 请求头大小裁剪（防日志污染） | request_id 截断到 64 字符 | ✅ 已实现 |
| 容器非 root 运行、多阶段构建 | `Dockerfile` | ✅ 已实现 |
| JWT 认证（HS256，算法白名单） | `dw_domain/security.py` + `dw_api/auth.py` | ✅ Phase 1 |
| RBAC：角色 → 权限数据驱动绑定 | `users/roles/permissions` 表 + `rbac_defaults.py` | ✅ Phase 1 |
| Project ACL：项目成员 + tool scope 双重判定 | `dw_domain/access_control.py`（纯函数，全矩阵单测） | ✅ Phase 1 |
| 口令散列 PBKDF2-HMAC-SHA256（600k 迭代 + 随机盐） | `dw_domain/security.py` | ✅ Phase 1 |
| 登录失败不区分「邮箱不存在 / 口令错误」 | `AuthService.authenticate`（防用户枚举） | ✅ Phase 1 |
| 账号停用后令牌立即失效 | `/auth/me` 回查数据库 | ✅ Phase 1 |

## 尚未实现（不得视为已完成）

需求文档 §13 要求的下列能力属于后续 Phase，当前代码**不具备**：

| 能力 | 计划 Phase |
|------|-----------|
| Tool Scope 鉴权与审计（ToolExecutor 层） | Phase 2 |
| 幂等 / 重试 / 降级 / 审计日志（工具治理） | Phase 2 |
| Prompt Injection 防御策略 | Phase 3 |
| Agent 沙箱（禁止任意代码执行） | Phase 2 |

健康检查端点当前**无需认证**，这是有意为之：它们要被容器编排系统访问。
其余业务端点在 Phase 1 引入 JWT 后默认要求登录。

---

## 部署安全清单

- [ ] `APP_ENV=production`、`APP_DEBUG=false`
- [ ] `SECRET_KEY` 使用 32 位以上随机串（`openssl rand -hex 32`）
- [ ] `CORS_ORIGINS` 显式列出前端域名（禁止 `*`）
- [ ] 数据库 / Redis / Kafka 启用认证并限制网络可达
- [ ] 前置 TLS 终止（HTTPS）与 WAF
- [ ] 不再依赖 compose 默认账号口令，改为密钥管理服务下发
- [ ] 开启 Phase 9 的可观测配置后再上线生产环境
