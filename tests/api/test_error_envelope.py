"""统一错误信封 HTTP 层测试 —— 需求文档 §25。"""

from __future__ import annotations

import pytest
from dw_api.app import API_PREFIX, create_app
from dw_api.errors import (
    ApiError,
    InternalServerError,
    ToolPermissionError,
    ToolTimeoutError,
)
from dw_infrastructure.config import Settings
from dw_schemas.envelope import ErrorCategory, ErrorCode
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    application = create_app(Settings(app_env="testing", log_json=False, log_level="WARNING"))

    @application.get(f"{API_PREFIX}/boom")
    async def boom() -> dict[str, str]:
        raise InternalServerError("演示内部错误", details={"hint": "never-happens"})

    @application.get(f"{API_PREFIX}/tool-timeout")
    async def tool_timeout() -> dict[str, str]:
        raise ToolTimeoutError("材料价格查询超时", details={"tool_id": "search_material_price"})

    @application.get(f"{API_PREFIX}/tool-denied")
    async def tool_denied() -> dict[str, str]:
        raise ToolPermissionError("当前角色无权调用该工具")

    @application.get(f"{API_PREFIX}/validated")
    async def validated(quantity: int) -> dict[str, int]:
        return {"quantity": quantity}

    @application.get(f"{API_PREFIX}/unexpected")
    async def unexpected() -> dict[str, str]:
        raise ValueError("kaboom")

    return TestClient(application, raise_server_exceptions=False)


def api_error_app(client: TestClient) -> FastAPI:
    return client.app  # type: ignore[return-value]


def test_internal_error_shape(client):
    response = client.get(f"{API_PREFIX}/boom", headers={"X-Request-ID": "rid-1"})
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == ErrorCode.INTERNAL_ERROR.value
    assert body["category"] == ErrorCategory.INTERNAL.value
    assert body["message"] == "演示内部错误"
    assert body["request_id"] == "rid-1"
    assert body["retryable"] is False
    assert body["details"] == {"hint": "never-happens"}


def test_tool_timeout_maps_to_504_and_retryable(client):
    response = client.get(f"{API_PREFIX}/tool-timeout")
    assert response.status_code == 504
    body = response.json()
    assert body["code"] == ErrorCode.TOOL_TIMEOUT.value
    assert body["category"] == ErrorCategory.TOOL.value
    assert body["retryable"] is True


def test_tool_permission_denied_maps_to_403(client):
    response = client.get(f"{API_PREFIX}/tool-denied")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == ErrorCode.TOOL_PERMISSION_DENIED.value
    assert body["retryable"] is False


def test_request_validation_uses_validation_envelope(client):
    response = client.get(f"{API_PREFIX}/validated", params={"quantity": "not-a-number"})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.VALIDATION_ERROR.value
    assert body["category"] == ErrorCategory.VALIDATION.value
    problems = body["details"]["problems"]
    assert problems, "必须给出具体字段级原因"
    assert problems[0]["field"]


def test_missing_required_query_param_is_validation_error(client):
    response = client.get(f"{API_PREFIX}/validated")
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value


def test_unknown_path_returns_not_found_envelope(client):
    response = client.get(f"{API_PREFIX}/definitely-not-exists")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == ErrorCode.RESOURCE_NOT_FOUND.value
    assert body["request_id"] == "-"
    assert set(body) >= {"code", "message", "request_id", "retryable"}


def test_unexpected_exception_is_normalized_and_does_not_leak_details(client):
    response = client.get(f"{API_PREFIX}/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == ErrorCode.INTERNAL_ERROR.value
    assert body["message"] == "服务内部发生未预期的错误"
    assert body["details"] == {"error_type": "ValueError"}
    # 原始异常消息不得出现在响应体里
    assert "kaboom" not in response.text


def test_api_error_defaults_to_spec_message():
    error = ToolTimeoutError()
    assert error.message == "工具调用超时"
    assert error.http_status == 504
    assert error.to_envelope("rid").code == ErrorCode.TOOL_TIMEOUT.value


def test_api_error_requires_known_code():
    class Unregistered(ApiError):
        pass

    # 未覆写 code 时沿用 INTERNAL_ERROR，但绝不允许动态编造错误码
    assert Unregistered("x").code is ErrorCode.INTERNAL_ERROR
