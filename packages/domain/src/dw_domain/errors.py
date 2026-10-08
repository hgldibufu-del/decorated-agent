"""领域异常。

分层约定：领域层抛**自己的**异常，由 `apps/api` 映射到 HTTP 错误信封。
领域层不认识 HTTP 状态码，接入层不认识 ORM —— 两侧互不泄漏。
"""

from __future__ import annotations


class DomainError(Exception):
    """领域层异常基类。"""


# -----------------------------------------------------------------------------
# 认证
# -----------------------------------------------------------------------------
class AuthenticationError(DomainError):
    """未能确认调用者身份。"""


class InvalidCredentialsError(AuthenticationError):
    """邮箱不存在或口令错误（对外不区分，避免用户枚举）。"""


class InactiveUserError(AuthenticationError):
    """账号已停用。"""


class TokenError(AuthenticationError):
    """令牌本身有问题。"""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


# -----------------------------------------------------------------------------
# 授权
# -----------------------------------------------------------------------------
class AuthorizationError(DomainError):
    """身份有效，但没有相应权限。"""


class PermissionDeniedError(AuthorizationError):
    pass


# -----------------------------------------------------------------------------
# 资源
# -----------------------------------------------------------------------------
class EntityNotFoundError(DomainError):
    """实体不存在（注意：对无权访问的资源也应回答「不存在」，见 services 注释）。"""


# -----------------------------------------------------------------------------
# 工具治理（§12）
#
# 命名刻意与 dw_schemas.ErrorCode 的 TOOL_* 系列一一对应。
# 注意：apps/api 里有同名的 ApiError 子类，接入层映射时必须用别名导入。
# -----------------------------------------------------------------------------
class ToolError(DomainError):
    """工具调用失败。"""


class ToolTimeoutError(ToolError):
    pass


class ToolPermissionError(ToolError):
    pass


class ToolValidationError(ToolError):
    pass


class ToolUnavailableError(ToolError):
    """工具未注册、被禁用或下游不可用。"""


class ToolConflictError(ToolError):
    """幂等冲突：同一 idempotency_key 已有进行中的调用。"""


class PlanValidationError(DomainError):
    """执行计划不合法：超上限、依赖缺失、存在环等（§32）。"""


class UnsupportedIntentError(DomainError):
    """意图已识别，但所需 Agent / Skill 尚未注册。"""

    def __init__(self, intent: str, missing: str) -> None:
        self.intent = intent
        self.missing = missing
        super().__init__(f"暂不支持意图 {intent}：缺少 {missing}")


class RegistryValidationError(DomainError):
    """注册中心校验失败：Agent 不支持该 Skill / Skill 不允许该 Tool。"""


class InvalidOperationError(DomainError):
    """业务规则不允许的操作（如：把不属于该客户的房屋挂到项目上）。"""


class DuplicateEntityError(DomainError):
    """违反唯一约束。"""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} 已存在: {value}")


class StaleObjectError(DomainError):
    """乐观锁冲突：目标对象已被其他人修改。"""

    def __init__(self, entity: str, expected: int, actual: int | None) -> None:
        self.entity = entity
        self.expected = expected
        self.actual = actual
        super().__init__(f"{entity} 版本冲突: 期望 {expected}, 实际 {actual}")


class EntityInUseError(DomainError):
    """实体被其它业务事实引用，不允许删除（对应外键 RESTRICT）。

    业务事实（客户 / 房屋 / 项目及其 Run）不允许被连坐删除，因此删除被引用对象
    必须明确失败，而不是级联抹除历史。
    """

    def __init__(self, entity: str, referenced_by: str) -> None:
        self.entity = entity
        self.referenced_by = referenced_by
        super().__init__(f"{entity} 仍被 {referenced_by} 引用，无法删除")
