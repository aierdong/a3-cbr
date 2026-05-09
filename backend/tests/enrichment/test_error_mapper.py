"""ErrorMapper 单元测试。

覆盖：
- LLMClientError 各 error_code 映射到正确的 HTTP 503 响应
- OutputValidationException 映射到 HTTP 503
- 未知异常映射到 HTTP 500
- 响应结构匹配 ErrorResponse 格式

Requirements: 5.3, 5.4, 5.5, 6.4
Boundary: ErrorMapper
"""

import pytest

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode, ErrorMapper, ErrorResponse
from app.enrichment.validators import OutputValidationException, ValidationErrorCode


# ---------------------------------------------------------------------------
# LLMClientError -> HTTP 503 测试
# ---------------------------------------------------------------------------


class TestLLMClientErrorMapping:
    """LLMClientError 各 error_code 应映射为 HTTP 503 + 对应 ErrorCode。"""

    @pytest.mark.parametrize(
        "error_code,expected_code",
        [
            (ErrorCode.LLM_TIMEOUT, ErrorCode.LLM_TIMEOUT),
            (ErrorCode.LLM_RATE_LIMITED, ErrorCode.LLM_RATE_LIMITED),
            (ErrorCode.LLM_PROVIDER_ERROR, ErrorCode.LLM_PROVIDER_ERROR),
            (ErrorCode.LLM_PRIVACY_CONFIG_MISSING, ErrorCode.LLM_PRIVACY_CONFIG_MISSING),
            (ErrorCode.LLM_INVALID_RESPONSE, ErrorCode.LLM_INVALID_RESPONSE),
        ],
        ids=[
            "LLM_TIMEOUT",
            "LLM_RATE_LIMITED",
            "LLM_PROVIDER_ERROR",
            "LLM_PRIVACY_CONFIG_MISSING",
            "LLM_INVALID_RESPONSE",
        ],
    )
    def test_llm_client_error_maps_to_503(
        self,
        error_code: str,
        expected_code: str,
    ) -> None:
        """LLMClientError 应映射为 HTTP 503 且保留原始 error_code。"""
        exc = LLMClientError(error_code=error_code, message="test failure")
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.status_code == 503
        assert isinstance(result.detail, dict)
        assert result.detail["code"] == expected_code
        assert result.detail["message"] == "test failure"

    def test_llm_client_error_preserves_retryable_in_meta(self) -> None:
        """LLMClientError 的 retryable 属性应出现在 meta 中。"""
        exc = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="timeout",
            retryable=True,
        )
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.detail["meta"]["retryable"] is True


# ---------------------------------------------------------------------------
# OutputValidationException -> HTTP 503 测试
# ---------------------------------------------------------------------------


class TestOutputValidationExceptionMapping:
    """OutputValidationException 应映射为 HTTP 503。"""

    def test_validation_error_maps_to_503(self) -> None:
        """OutputValidationException 应映射为 HTTP 503 + LLM_INVALID_RESPONSE。"""
        exc = OutputValidationException(
            error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
            message="JSON parse failed",
        )
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.status_code == 503
        assert result.detail["code"] == ErrorCode.LLM_INVALID_RESPONSE

    def test_injection_suspected_maps_to_503(self) -> None:
        """注入嫌疑校验异常应映射为 HTTP 503 + INJECTION_SUSPECTED。"""
        exc = OutputValidationException(
            error_code=ValidationErrorCode.INJECTION_SUSPECTED,
            message="injection detected",
        )
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.status_code == 503
        assert result.detail["code"] == "INJECTION_SUSPECTED"

    def test_validation_error_includes_field_details(self) -> None:
        """校验错误的 fields 列表应出现在响应中。"""
        from app.enrichment.validators import ValidationError

        exc = OutputValidationException(
            error_code=ValidationErrorCode.MISSING_FIELD,
            message="missing field",
            errors=[
                ValidationError(field="items[0].reason", message="required", code="MISSING_FIELD"),
            ],
        )
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.status_code == 503
        assert result.detail["code"] == ErrorCode.LLM_INVALID_RESPONSE
        assert len(result.detail["fields"]) == 1
        assert result.detail["fields"][0]["field"] == "items[0].reason"


# ---------------------------------------------------------------------------
# 未知异常 -> HTTP 500 测试
# ---------------------------------------------------------------------------


class TestUnexpectedExceptionMapping:
    """未知异常应映射为 HTTP 500。"""

    def test_generic_exception_maps_to_500(self) -> None:
        """任意非 LLM/校验异常应映射为 HTTP 500。"""
        exc = RuntimeError("something broke")
        mapper = ErrorMapper()

        result = mapper.to_http_exception(exc)

        assert result.status_code == 500
        assert result.detail["code"] == ErrorCode.INTERNAL_ERROR
        assert "unexpected" in result.detail["message"].lower()


# ---------------------------------------------------------------------------
# ErrorResponse 结构校验
# ---------------------------------------------------------------------------


class TestResponseStructure:
    """所有映射结果应可合法构造 ErrorResponse。"""

    def test_llm_error_detail_is_valid_response(self) -> None:
        """LLM 异常映射结果可反序列化为 ErrorResponse。"""
        exc = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="timeout",
        )
        mapper = ErrorMapper()
        result = mapper.to_http_exception(exc)

        # detail 应能反序列化为 ErrorResponse
        response = ErrorResponse(**result.detail)
        assert response.code == ErrorCode.LLM_TIMEOUT

    def test_validation_error_detail_is_valid_response(self) -> None:
        """校验异常映射结果可反序列化为 ErrorResponse。"""
        exc = OutputValidationException(
            error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
            message="invalid",
        )
        mapper = ErrorMapper()
        result = mapper.to_http_exception(exc)

        response = ErrorResponse(**result.detail)
        assert response.code == ErrorCode.LLM_INVALID_RESPONSE

    def test_unexpected_error_detail_is_valid_response(self) -> None:
        """未知异常映射结果可反序列化为 ErrorResponse。"""
        exc = ValueError("oops")
        mapper = ErrorMapper()
        result = mapper.to_http_exception(exc)

        response = ErrorResponse(**result.detail)
        assert response.code == ErrorCode.INTERNAL_ERROR
