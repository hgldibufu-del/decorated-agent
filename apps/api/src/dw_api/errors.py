"""统一错误处理 —— 需求文档 §25。

规则：
* 业务代码抛 `ApiError` 子类，Handler 统一转成 `ErrorEnvelope`；
* code / category / retryable / http_status 一律由 `ERROR_SPECS` 推导，
  避免「同一错误码在不同端点返回不同状态码」；
* 未捕获异常归一化为 INTERNAL_ERROR，但**必须记录完整堆栈**，严禁静默。
"""

from __future__ import annotations

import logging
from typing import Any

from dw_domain.errors import (
    DomainError,
    DuplicateEntityError,
    EntityInUseError,
    EntityNotFoundError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidOperationError,
    RegistryValidationError,
    StaleObjectError,
    TokenError,
)
from dw_domain.errors import (
    # 下面还定义了同名的 ApiError 子类，领域异常必须加前缀导入，否则会被覆盖
    PermissionDeniedError as DomainPermissionDeniedError,
)
from dw_domain.errors import (
    PlanValidationError as DomainPlanValidationError,
)
from dw_domain.errors import (
    ToolConflictError as DomainToolConflictError,
)
from dw_domain.errors import (
    ToolError as DomainToolError,
)
from dw_domain.errors import (
    ToolPermissionError as DomainToolPermissionError,
)
from dw_domain.errors import (
    ToolTimeoutError as DomainToolTimeoutError,
)
from dw_domain.errors import (
    ToolUnavailableError as DomainToolUnavailableError,
)
from dw_domain.errors import (
    ToolValidationError as DomainToolValidationError,
)
from dw_domain.errors import (
    UnsupportedIntentError as DomainUnsupportedIntentError,
)
from dw_schemas.envelope import (
    ERROR_SPECS,
    REQUEST_ID_HEADER,
    ErrorCode,
    ErrorEnvelope,
    http_status_for,
)
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Starlette 原生状态码 → 业务错误码（让 404/405 也走统一信封）
_HTTP_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.AUTHENTICATION_REQUIRED,
    status.HTTP_403_FORBIDDEN: ErrorCode.PERMISSION_DENIED,
    status.HTTP_404_NOT_FOUND: ErrorCode.RESOURCE_NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
}


class ApiError(Exception):
    """业务异常基类。所有已识别错误都必须显式落到某个 ErrorCode。"""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.message = message or ERROR_SPECS[self.code].default_message
        self.details: dict[str, Any] = dict(details or {})
        self.cause = cause
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return http_status_for(self.code)

    def to_envelope(self, request_id: str) -> ErrorEnvelope:
        return ErrorEnvelope.from_code(
            self.code, message=self.message, request_id=request_id, details=self.details
        )


# -----------------------------------------------------------------------------
# 具体错误族
# -----------------------------------------------------------------------------
class ValidationFailedError(ApiError):
    code = ErrorCode.VALIDATION_ERROR


class AuthenticationRequiredError(ApiError):
    code = ErrorCode.AUTHENTICATION_REQUIRED


class PermissionDeniedError(ApiError):
    code = ErrorCode.PERMISSION_DENIED


class ResourceNotFoundError(ApiError):
    code = ErrorCode.RESOURCE_NOT_FOUND


class ResourceConflictError(ApiError):
    code = ErrorCode.CONFLICT


class RateLimitedError(ApiError):
    code = ErrorCode.RATE_LIMITED


# §12 工具治理错误族：由 ToolExecutor 抛出，供 Agent 决定 retry / fallback
class ToolTimeoutError(ApiError):
    code = ErrorCode.TOOL_TIMEOUT


class ToolPermissionError(ApiError):
    code = ErrorCode.TOOL_PERMISSION_DENIED


class ToolValidationError(ApiError):
    code = ErrorCode.TOOL_VALIDATION_ERROR


class ToolUnavailableError(ApiError):
    code = ErrorCode.TOOL_UNAVAILABLE


class ToolConflictError(ApiError):
    code = ErrorCode.TOOL_CONFLICT


class ModelCallError(ApiError):
    code = ErrorCode.MODEL_ERROR


class DatabaseUnavailableError(ApiError):
    code = ErrorCode.DATABASE_ERROR


class DependencyUnavailableError(ApiError):
    code = ErrorCode.DEPENDENCY_UNAVAILABLE


class InternalServerError(ApiError):
    code = ErrorCode.INTERNAL_ERROR


# -----------------------------------------------------------------------------
# 响应构造
# -----------------------------------------------------------------------------
def _error_response(envelope: ErrorEnvelope, http_status: int) -> JSONResponse:
    """注意：不要再手动写 X-Request-ID 响应头。

    RequestContextMiddleware 已经统一注入；重复写入会让响应出现两个同名头。
    """
    return JSONResponse(
        status_code=http_status,
        content=envelope.model_dump(mode="json"),
    )


# -----------------------------------------------------------------------------
# 领域异常 → 错误码
#
# 领域层不认识 HTTP，这里做唯一的一次映射。映射表是**显式**的：
# 新增领域异常必须在这里登记，否则会被兜底成 INTERNAL_ERROR 并在日志里留下线索。
# -----------------------------------------------------------------------------
DOMAIN_ERROR_CODES: dict[type[DomainError], ErrorCode] = {
    EntityNotFoundError: ErrorCode.RESOURCE_NOT_FOUND,
    DuplicateEntityError: ErrorCode.CONFLICT,
    InvalidOperationError: ErrorCode.VALIDATION_ERROR,
    InvalidCredentialsError: ErrorCode.AUTHENTICATION_REQUIRED,
    InactiveUserError: ErrorCode.AUTHENTICATION_REQUIRED,
    TokenError: ErrorCode.AUTHENTICATION_REQUIRED,
    DomainPermissionDeniedError: ErrorCode.PERMISSION_DENIED,
    RegistryValidationError: ErrorCode.VALIDATION_ERROR,
    DomainPlanValidationError: ErrorCode.PLAN_INVALID,
    DomainUnsupportedIntentError: ErrorCode.CAPABILITY_NOT_IMPLEMENTED,
    StaleObjectError: ErrorCode.CONFLICT,
    EntityInUseError: ErrorCode.CONFLICT,
    # 工具治理错误族：顺序不能颠倒，子类必须排在基类之前
    DomainToolTimeoutError: ErrorCode.TOOL_TIMEOUT,
    DomainToolPermissionError: ErrorCode.TOOL_PERMISSION_DENIED,
    DomainToolValidationError: ErrorCode.TOOL_VALIDATION_ERROR,
    DomainToolConflictError: ErrorCode.TOOL_CONFLICT,
    DomainToolUnavailableError: ErrorCode.TOOL_UNAVAILABLE,
    DomainToolError: ErrorCode.TOOL_UNAVAILABLE,
}


def install_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，确保所有出口都是 ErrorEnvelope。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER, "-")
        logger.warning(
            "api error",
            extra={
                "error_code": exc.code.value,
                "http_status": exc.http_status,
                "path": request.url.path,
                "details": exc.details,
            },
        )
        return _error_response(exc.to_envelope(request_id), exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER, "-")
        problems = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        envelope = ErrorEnvelope.from_code(
            ErrorCode.VALIDATION_ERROR,
            message="请求参数校验失败",
            request_id=request_id,
            details={"problems": problems},
        )
        return _error_response(envelope, http_status_for(ErrorCode.VALIDATION_ERROR))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER, "-")
        code = _HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        envelope = ErrorEnvelope.from_code(code, message=str(exc.detail), request_id=request_id)
        return _error_response(envelope, http_status_for(code))

    def make_domain_handler(code: ErrorCode):
        async def handler(request: Request, exc: DomainError) -> JSONResponse:
            request_id = request.headers.get(REQUEST_ID_HEADER, "-")
            details: dict[str, Any] = {"error_type": type(exc).__name__}
            if isinstance(exc, DuplicateEntityError):
                details = {"field": exc.field, "value": exc.value}
            logger.info(
                "domain error",
                extra={
                    "error_code": code.value,
                    "domain_error": type(exc).__name__,
                    "path": request.url.path,
                },
            )
            return _error_response(
                ErrorEnvelope.from_code(
                    code, message=str(exc), request_id=request_id, details=details
                ),
                http_status_for(code),
            )

        return handler

    for domain_error_type, error_code in DOMAIN_ERROR_CODES.items():
        app.add_exception_handler(domain_error_type, make_domain_handler(error_code))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER, "-")
        logger.exception(
            "unhandled exception",
            extra={"path": request.url.path, "error_type": type(exc).__name__},
        )
        envelope = ErrorEnvelope.from_code(
            ErrorCode.INTERNAL_ERROR,
            message="服务内部发生未预期的错误",
            request_id=request_id,
            details={"error_type": type(exc).__name__},
        )
        return _error_response(envelope, http_status_for(ErrorCode.INTERNAL_ERROR))
