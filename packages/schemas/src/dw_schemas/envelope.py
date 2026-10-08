"""统一错误契约 —— 需求文档 §25。

要求：
* 所有错误必须使用同一个信封形状，前端只需处理一种结构；
* 必须能区分 6 类错误源头：user / validation / permission / tool / model / database
  （另加 infrastructure 与兜底 internal）；
* 必须告诉调用方「是否值得重试」。

约束（Rule 4）：所有 ErrorCode 都必须在 ERROR_SPECS 中有真实定义，
不允许出现未登记的错误码。make-default / except-pass 式的吞异常在此无处藏身。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"


# -----------------------------------------------------------------------------
# 错误分类：回答「这是谁的问题」
# -----------------------------------------------------------------------------
class ErrorCategory(str, Enum):
    """错误源头分类，用于告警路由与排查方向判断。"""

    USER = "user_error"
    VALIDATION = "validation_error"
    PERMISSION = "permission_error"
    TOOL = "tool_error"
    MODEL = "model_error"
    DATABASE = "database_error"
    INFRASTRUCTURE = "infrastructure_error"
    NOT_IMPLEMENTED = "not_implemented"
    INTERNAL = "internal_error"


# -----------------------------------------------------------------------------
# 错误码：回答「具体出错了什么」
# -----------------------------------------------------------------------------
class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"

    # §12 工具治理错误族
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    TOOL_VALIDATION_ERROR = "TOOL_VALIDATION_ERROR"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_CONFLICT = "TOOL_CONFLICT"

    CAPABILITY_NOT_IMPLEMENTED = "CAPABILITY_NOT_IMPLEMENTED"
    PLAN_INVALID = "PLAN_INVALID"
    MODEL_ERROR = "MODEL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """单个错误码的静态行为定义。"""

    category: ErrorCategory
    http_status: int
    retryable: bool
    default_message: str


ERROR_SPECS: Final[Mapping[ErrorCode, ErrorSpec]] = {
    ErrorCode.VALIDATION_ERROR: ErrorSpec(ErrorCategory.VALIDATION, 400, False, "请求参数校验失败"),
    ErrorCode.AUTHENTICATION_REQUIRED: ErrorSpec(
        ErrorCategory.PERMISSION, 401, False, "需要认证后才能访问"
    ),
    ErrorCode.PERMISSION_DENIED: ErrorSpec(
        ErrorCategory.PERMISSION, 403, False, "没有访问该资源的权限"
    ),
    ErrorCode.RESOURCE_NOT_FOUND: ErrorSpec(ErrorCategory.USER, 404, False, "资源不存在"),
    ErrorCode.CONFLICT: ErrorSpec(ErrorCategory.USER, 409, False, "资源状态冲突"),
    ErrorCode.RATE_LIMITED: ErrorSpec(
        ErrorCategory.INFRASTRUCTURE, 429, True, "请求过于频繁，请稍后重试"
    ),
    ErrorCode.TOOL_TIMEOUT: ErrorSpec(ErrorCategory.TOOL, 504, True, "工具调用超时"),
    ErrorCode.TOOL_PERMISSION_DENIED: ErrorSpec(
        ErrorCategory.TOOL, 403, False, "当前角色无权调用该工具"
    ),
    ErrorCode.TOOL_VALIDATION_ERROR: ErrorSpec(ErrorCategory.TOOL, 400, False, "工具入参校验失败"),
    ErrorCode.TOOL_UNAVAILABLE: ErrorSpec(ErrorCategory.TOOL, 503, True, "工具当前不可用"),
    ErrorCode.TOOL_CONFLICT: ErrorSpec(
        ErrorCategory.TOOL, 409, True, "工具幂等冲突：相同请求正在处理"
    ),
    ErrorCode.CAPABILITY_NOT_IMPLEMENTED: ErrorSpec(
        ErrorCategory.NOT_IMPLEMENTED, 501, False, "所需能力尚未实现"
    ),
    ErrorCode.PLAN_INVALID: ErrorSpec(ErrorCategory.VALIDATION, 400, False, "执行计划不合法"),
    ErrorCode.MODEL_ERROR: ErrorSpec(ErrorCategory.MODEL, 502, True, "模型调用失败"),
    ErrorCode.DATABASE_ERROR: ErrorSpec(ErrorCategory.DATABASE, 503, True, "数据库访问失败"),
    ErrorCode.DEPENDENCY_UNAVAILABLE: ErrorSpec(
        ErrorCategory.INFRASTRUCTURE, 503, True, "依赖组件不可用"
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        ErrorCategory.INTERNAL, 500, False, "服务内部发生未预期的错误"
    ),
}


class ErrorEnvelope(BaseModel):
    """统一错误响应体。

    需求 §25 规定的四个必填字段：code / message / request_id / retryable。
    category 与 details 为可选增强，用于前端区分告警路由。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "code": "TOOL_TIMEOUT",
                    "message": "材料价格查询超时",
                    "request_id": "b3f1e2d4c5a647d8a1e0f9c2b3d4e5f6",
                    "retryable": True,
                    "category": "tool_error",
                    "details": {"tool_id": "search_material_price"},
                }
            ]
        },
    )

    code: str = Field(..., description="稳定机器可读的错误码")
    message: str = Field(..., description="面向调用方的可读信息")
    request_id: str = Field(..., description="贯穿日志 / Trace / 审计的请求标识")
    retryable: bool = Field(..., description="客户端是否可以安全重试")
    category: ErrorCategory = Field(default=ErrorCategory.INTERNAL, description="错误源头分类")
    details: dict[str, Any] = Field(default_factory=dict, description="结构化补充信息")

    @classmethod
    def from_code(
        cls,
        code: ErrorCode,
        *,
        message: str | None = None,
        request_id: str = "-",
        details: dict[str, Any] | None = None,
    ) -> ErrorEnvelope:
        """按错误码的静态定义构造信封，保证 code / category / retryable 永远一致。"""
        spec = ERROR_SPECS[code]
        return cls(
            code=code.value,
            message=message or spec.default_message,
            request_id=request_id,
            retryable=spec.retryable,
            category=spec.category,
            details=details or {},
        )


# -----------------------------------------------------------------------------
# 查询工具
# -----------------------------------------------------------------------------
def http_status_for(code: ErrorCode) -> int:
    return ERROR_SPECS[code].http_status


def category_for(code: ErrorCode) -> ErrorCategory:
    return ERROR_SPECS[code].category


def is_retryable(code: ErrorCode) -> bool:
    return ERROR_SPECS[code].retryable
