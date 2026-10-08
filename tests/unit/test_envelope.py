"""统一错误契约单测 —— 需求文档 §25。"""

from __future__ import annotations

import pytest
from dw_schemas.envelope import (
    ERROR_SPECS,
    ErrorCategory,
    ErrorCode,
    ErrorEnvelope,
    category_for,
    http_status_for,
    is_retryable,
)
from pydantic import ValidationError


def test_every_error_code_has_a_spec():
    """防止出现未登记的错误码：新增 ErrorCode 必须同时登记 ErrorSpec。"""
    missing = [code for code in ErrorCode if code not in ERROR_SPECS]
    assert missing == []


def test_error_specs_are_internally_consistent():
    for code, spec in ERROR_SPECS.items():
        assert 400 <= spec.http_status <= 599, f"{code} 状态码越界"
        assert spec.default_message, f"{code} 缺少默认消息"
        assert isinstance(spec.category, ErrorCategory)


@pytest.mark.parametrize(
    "code",
    list(ErrorCode),
)
def test_category_and_retryable_helpers_agree_with_specs(code: ErrorCode):
    assert http_status_for(code) == ERROR_SPECS[code].http_status
    assert category_for(code) == ERROR_SPECS[code].category
    assert is_retryable(code) == ERROR_SPECS[code].retryable


def test_tool_errors_are_the_tool_category():
    """§12 定义的工具错误族必须落在 tool_error 分类。"""
    tool_codes = [
        ErrorCode.TOOL_TIMEOUT,
        ErrorCode.TOOL_PERMISSION_DENIED,
        ErrorCode.TOOL_VALIDATION_ERROR,
        ErrorCode.TOOL_UNAVAILABLE,
        ErrorCode.TOOL_CONFLICT,
    ]
    assert {category_for(code) for code in tool_codes} == {ErrorCategory.TOOL}


def test_envelope_shape_matches_requirement_sample():
    """需求文档给出的样例字段必须完全存在。"""
    envelope = ErrorEnvelope.from_code(
        ErrorCode.TOOL_TIMEOUT,
        message="材料价格查询超时",
        request_id="xxx",
    )
    payload = envelope.model_dump()
    assert set(payload) >= {"code", "message", "request_id", "retryable"}
    assert payload["code"] == "TOOL_TIMEOUT"
    assert payload["message"] == "材料价格查询超时"
    assert payload["request_id"] == "xxx"
    assert payload["retryable"] is True


def test_envelope_defaults_to_spec_message():
    envelope = ErrorEnvelope.from_code(ErrorCode.TOOL_TIMEOUT, request_id="-")
    assert envelope.message == ERROR_SPECS[ErrorCode.TOOL_TIMEOUT].default_message


def test_permission_errors_are_not_retryable():
    for code in (
        ErrorCode.PERMISSION_DENIED,
        ErrorCode.AUTHENTICATION_REQUIRED,
        ErrorCode.TOOL_PERMISSION_DENIED,
    ):
        assert is_retryable(code) is False


def test_envelope_requires_core_fields():
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate({"code": "TOOL_TIMEOUT"})


def test_unknown_spec_lookup_fails_loudly():
    """不允许隐式兜底：查询未登记的码必须抛异常，而不是返回默认值。"""
    with pytest.raises(KeyError):
        http_status_for("NOT_A_REAL_CODE")  # type: ignore[arg-type]
