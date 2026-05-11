"""统一错误响应定义。.

定义 A3 案例管理系统的错误码和错误结构。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel

if TYPE_CHECKING:
    from app.common.llm_client import LLMClientError
    from app.enrichment.validators import OutputValidationException

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """字段级错误详情。."""

    field: str
    message: str


class ErrorResponse(BaseModel):
    """统一错误响应结构。."""

    code: str
    message: str
    fields: list[ErrorDetail] = []
    meta: dict = {}


# 错误码定义
class ErrorCode:
    """错误码常量。."""

    # 校验错误 (422)
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 资源未找到
    STORE_NOT_FOUND = "STORE_NOT_FOUND"  # 400: store_id 在 store_infos 中不存在
    CASE_NOT_FOUND = "CASE_NOT_FOUND"  # 404: case_id 不存在

    # 状态冲突 (409)
    CASE_STATE_CONFLICT = "CASE_STATE_CONFLICT"

    # 系统错误 (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # --- LLM 增强相关错误码 ---

    # 案例增强资源错误 (404/409)
    ENRICHMENT_RUN_NOT_FOUND = "ENRICHMENT_RUN_NOT_FOUND"  # 404: 增强运行不存在
    ENRICHMENT_STATE_CONFLICT = "ENRICHMENT_STATE_CONFLICT"  # 409: 案例状态不可增强（如 draft）
    ENRICHMENT_RETRY_NOT_FOUND = "ENRICHMENT_RETRY_NOT_FOUND"  # 404: 重试目标运行不存在
    ENRICHMENT_RETRY_NOT_ALLOWED = "ENRICHMENT_RETRY_NOT_ALLOWED"  # 409: 当前状态不允许重试

    # Prompt 注入检测
    INJECTION_RISK_DETECTED = "INJECTION_RISK_DETECTED"  # 200: 高风险注入模式，阻断请求
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"  # 校验阶段: 输出侧注入嫌疑

    # LLM 供应商错误 (503)
    LLM_TIMEOUT = "LLM_TIMEOUT"  # 503: LLM 调用超时
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"  # 503: LLM 限流
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"  # 503: 供应商故障
    LLM_PRIVACY_CONFIG_MISSING = "LLM_PRIVACY_CONFIG_MISSING"  # 503: 隐私配置缺失
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"  # 503: LLM 输出无法解析或校验失败

    # --- 向量索引与 embedding（case-vector-indexing） ---

    VECTOR_JOB_NOT_FOUND = "VECTOR_JOB_NOT_FOUND"
    VECTOR_STATE_CONFLICT = "VECTOR_STATE_CONFLICT"
    VECTOR_CONFLICT = "VECTOR_CONFLICT"
    VECTOR_RETRY_NOT_ALLOWED = "VECTOR_RETRY_NOT_ALLOWED"
    VECTOR_INPUT_INSUFFICIENT = "VECTOR_INPUT_INSUFFICIENT"
    VECTOR_CASE_NOT_INDEXABLE = "VECTOR_CASE_NOT_INDEXABLE"
    VECTOR_PGVECTOR_UNAVAILABLE = "VECTOR_PGVECTOR_UNAVAILABLE"

    EMBEDDING_TIMEOUT = "EMBEDDING_TIMEOUT"
    EMBEDDING_RATE_LIMITED = "EMBEDDING_RATE_LIMITED"
    EMBEDDING_PROVIDER_ERROR = "EMBEDDING_PROVIDER_ERROR"
    EMBEDDING_INVALID_RESPONSE = "EMBEDDING_INVALID_RESPONSE"
    EMBEDDING_DIMENSION_MISMATCH = "EMBEDDING_DIMENSION_MISMATCH"
    EMBEDDING_CONFIG_MISSING = "EMBEDDING_CONFIG_MISSING"

    # --- cbr-retrieval-recommendation 检索相关错误码 ---

    # 检索禁用 / 配置缺失
    RETRIEVAL_DISABLED = "RETRIEVAL_DISABLED"  # 503: 检索功能未启用
    RETRIEVAL_CONFIG_MISSING = "RETRIEVAL_CONFIG_MISSING"  # 503: 生产配置缺失，fail-closed

    # 向量候选检索
    RETRIEVAL_VECTOR_FAILED = "RETRIEVAL_VECTOR_FAILED"  # 503: 向量搜索失败
    RETRIEVAL_VECTOR_TIMEOUT = "RETRIEVAL_VECTOR_TIMEOUT"  # 503: 向量搜索超时
    RETRIEVAL_VECTOR_UNAVAILABLE = "RETRIEVAL_VECTOR_UNAVAILABLE"  # 503: 向量搜索服务不可用
    RETRIEVAL_VECTOR_INVALID_RESPONSE = "RETRIEVAL_VECTOR_INVALID_RESPONSE"  # 503: 向量搜索响应无效

    # LLM Normalizer
    RETRIEVAL_NORMALIZER_FAILED = "RETRIEVAL_NORMALIZER_FAILED"  # 503: Normalizer LLM 调用失败
    RETRIEVAL_NORMALIZER_TIMEOUT = "RETRIEVAL_NORMALIZER_TIMEOUT"  # 503: Normalizer LLM 超时
    RETRIEVAL_NORMALIZER_RATE_LIMITED = "RETRIEVAL_NORMALIZER_RATE_LIMITED"
    RETRIEVAL_NORMALIZER_CONFIG_MISSING = "RETRIEVAL_NORMALIZER_CONFIG_MISSING"
    RETRIEVAL_NORMALIZER_INVALID_RESPONSE = "RETRIEVAL_NORMALIZER_INVALID_RESPONSE"

    # Reranker
    RETRIEVAL_RERANKER_FAILED = "RETRIEVAL_RERANKER_FAILED"
    RETRIEVAL_RERANKER_TIMEOUT = "RETRIEVAL_RERANKER_TIMEOUT"
    RETRIEVAL_RERANKER_RATE_LIMITED = "RETRIEVAL_RERANKER_RATE_LIMITED"
    RETRIEVAL_RERANKER_PROVIDER_ERROR = "RETRIEVAL_RERANKER_PROVIDER_ERROR"
    RETRIEVAL_RERANKER_CONFIG_MISSING = "RETRIEVAL_RERANKER_CONFIG_MISSING"
    RETRIEVAL_RERANKER_INVALID_RESPONSE = "RETRIEVAL_RERANKER_INVALID_RESPONSE"

    # 评分与聚合
    RETRIEVAL_AGGREGATION_FAILED = "RETRIEVAL_AGGREGATION_FAILED"  # 503: 分值聚合失败
    RETRIEVAL_STRUCTURED_SCORING_SKIPPED = "RETRIEVAL_STRUCTURED_SCORING_SKIPPED"
    RETRIEVAL_BUSINESS_SCORING_FAILED = "RETRIEVAL_BUSINESS_SCORING_FAILED"

    # 解释生成
    RETRIEVAL_EXPLANATION_FALLBACK = "RETRIEVAL_EXPLANATION_FALLBACK"  # 200: 解释降级（回退至 LLM）


_EMBEDDING_PUBLIC_MESSAGES: dict[str, str] = {
    ErrorCode.EMBEDDING_TIMEOUT: "Embedding 调用超时",
    ErrorCode.EMBEDDING_RATE_LIMITED: "Embedding 限流",
    ErrorCode.EMBEDDING_PROVIDER_ERROR: "Embedding 网关错误",
    ErrorCode.EMBEDDING_INVALID_RESPONSE: "Embedding 响应无法解析或校验失败",
    ErrorCode.EMBEDDING_DIMENSION_MISMATCH: "Embedding 向量维度与配置不一致",
    ErrorCode.EMBEDDING_CONFIG_MISSING: "Embedding 生产配置不完整或未确认隐私条款",
}

_RETRIEVAL_PUBLIC_MESSAGES: dict[str, str] = {
    ErrorCode.RETRIEVAL_DISABLED: "案例推荐检索功能未启用",
    ErrorCode.RETRIEVAL_CONFIG_MISSING: "案例推荐检索生产配置缺失",
    ErrorCode.RETRIEVAL_VECTOR_FAILED: "向量搜索失败",
    ErrorCode.RETRIEVAL_VECTOR_TIMEOUT: "向量搜索超时",
    ErrorCode.RETRIEVAL_VECTOR_UNAVAILABLE: "向量搜索服务不可用",
    ErrorCode.RETRIEVAL_VECTOR_INVALID_RESPONSE: "向量搜索响应无效",
    ErrorCode.RETRIEVAL_NORMALIZER_FAILED: "查询归一化 LLM 调用失败",
    ErrorCode.RETRIEVAL_NORMALIZER_TIMEOUT: "查询归一化 LLM 超时",
    ErrorCode.RETRIEVAL_NORMALIZER_RATE_LIMITED: "查询归一化 LLM 限流",
    ErrorCode.RETRIEVAL_NORMALIZER_CONFIG_MISSING: "查询归一化 LLM 配置缺失",
    ErrorCode.RETRIEVAL_NORMALIZER_INVALID_RESPONSE: "查询归一化 LLM 输出无效",
    ErrorCode.RETRIEVAL_RERANKER_FAILED: "重排模型调用失败",
    ErrorCode.RETRIEVAL_RERANKER_TIMEOUT: "重排模型超时",
    ErrorCode.RETRIEVAL_RERANKER_RATE_LIMITED: "重排模型限流",
    ErrorCode.RETRIEVAL_RERANKER_CONFIG_MISSING: "重排模型配置缺失",
    ErrorCode.RETRIEVAL_RERANKER_INVALID_RESPONSE: "重排模型输出无效",
    ErrorCode.RETRIEVAL_AGGREGATION_FAILED: "分值聚合失败",
    ErrorCode.RETRIEVAL_STRUCTURED_SCORING_SKIPPED: "结构化局部评分跳过",
    ErrorCode.RETRIEVAL_BUSINESS_SCORING_FAILED: "业务评分失败",
    ErrorCode.RETRIEVAL_EXPLANATION_FALLBACK: "解释生成降级",
}


def create_error_response(
    code: str,
    message: str,
    fields: Optional[list[ErrorDetail]] = None,
    meta: Optional[dict] = None,
) -> ErrorResponse:
    """创建错误响应。."""
    return ErrorResponse(
        code=code,
        message=message,
        fields=fields or [],
        meta=meta or {},
    )


# 映射 OutputValidationException.error_code 到统一 ErrorCode
_VALIDATION_TO_ERROR_CODE: dict[str, str] = {
    "INJECTION_SUSPECTED": ErrorCode.INJECTION_SUSPECTED,
    "LLM_INVALID_RESPONSE": ErrorCode.LLM_INVALID_RESPONSE,
    "MISSING_FIELD": ErrorCode.LLM_INVALID_RESPONSE,
    "INVALID_ENUM": ErrorCode.LLM_INVALID_RESPONSE,
    "CONSTRAINT_VIOLATION": ErrorCode.LLM_INVALID_RESPONSE,
    "CANDIDATE_MISMATCH": ErrorCode.LLM_INVALID_RESPONSE,
}


class ErrorMapper:
    """将服务层异常映射为统一 HTTP 错误响应。

    职责：
    - LLMClientError -> HTTP 503 + 对应 ErrorCode
    - OutputValidationException -> HTTP 503 + LLM_INVALID_RESPONSE（INJECTION_SUSPECTED 保留原码）
    - 未知异常 -> HTTP 500 + INTERNAL_ERROR

    供 enrichment router 端点复用，避免重复 try/except。
    """

    def to_http_exception(
        self,
        exc: Exception,
    ) -> HTTPException:
        """将异常映射为 HTTPException。

        Args:
            exc: 服务层抛出的异常。

        Returns:
            HTTPException: 包含统一错误响应结构的 HTTP 异常。
        """
        from app.common.llm_client import LLMClientError
        from app.enrichment.validators import OutputValidationException

        if isinstance(exc, LLMClientError):
            return self._map_llm_client_error(exc)

        if isinstance(exc, OutputValidationException):
            return self._map_output_validation_error(exc)

        return self._map_unexpected_error(exc)

    @staticmethod
    def _map_llm_client_error(exc: LLMClientError) -> HTTPException:
        """LLMClientError -> HTTP 503。"""
        meta: dict = {}
        if exc.retryable:
            meta["retryable"] = True

        public_message = _EMBEDDING_PUBLIC_MESSAGES.get(exc.error_code)
        if public_message is not None:
            logger.warning("LLM 调用失败: error_code=%s", exc.error_code)
            api_message = public_message
        else:
            logger.warning(
                "LLM 调用失败: error_code=%s, message=%s",
                exc.error_code,
                exc.message,
            )
            api_message = exc.message

        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=exc.error_code,
                message=api_message,
                meta=meta or None,
            ).model_dump(),
        )

    @staticmethod
    def _map_output_validation_error(
        exc: OutputValidationException,
    ) -> HTTPException:
        """OutputValidationException -> HTTP 503。"""
        mapped_code = _VALIDATION_TO_ERROR_CODE.get(
            exc.error_code,
            ErrorCode.LLM_INVALID_RESPONSE,
        )

        fields = [
            ErrorDetail(field=err.field, message=err.message)
            for err in exc.errors
        ] if exc.errors else None

        logger.warning(
            "输出校验失败: error_code=%s, message=%s",
            exc.error_code,
            exc.message,
        )

        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=mapped_code,
                message=exc.message,
                fields=fields,
            ).model_dump(),
        )

    @staticmethod
    def _map_unexpected_error(exc: Exception) -> HTTPException:
        """未知异常 -> HTTP 500。"""
        logger.error("意外异常: %s: %s", type(exc).__name__, exc)

        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="An unexpected error occurred",
            ).model_dump(),
        )
