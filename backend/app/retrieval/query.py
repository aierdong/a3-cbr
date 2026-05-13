"""QueryNormalizer：查询标准化、过滤条件校验与业务权重校验。

通过共享 LLMClient 执行单次 normalizer 外呼，产出标准化检索文本与查询侧结构化画像。
失败路径严格执行 Requirement 1.7（fail closed）。

Boundary: QueryNormalizer (uses shared LLMClient with NormalizerLLMConfig)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.llm_client import LLMClient, LLMClientError
from app.core.config import NormalizerLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    LLMCompletionRequest,
    LLM_RESPONSE_FORMAT_JSON_OBJECT,
    RequestPurpose,
    TaskType,
)
from app.retrieval.schemas import (
    BusinessWeights,
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
    RetrievalFilters,
    RetrievalRequest,
)


logger = logging.getLogger(__name__)


# =============================================================================
# Normalizer 专用异常
# =============================================================================


class NormalizerError(Exception):
    """LLM normalizer 基础异常。"""

    error_code: str = ErrorCode.RETRIEVAL_NORMALIZER_FAILED


class NormalizerTimeout(NormalizerError):
    """LLM normalizer 调用超时。"""

    error_code: str = ErrorCode.RETRIEVAL_NORMALIZER_TIMEOUT


class NormalizerRateLimited(NormalizerError):
    """LLM normalizer 限流。"""

    error_code: str = ErrorCode.RETRIEVAL_NORMALIZER_RATE_LIMITED


class NormalizerConfigMissing(NormalizerError):
    """LLM normalizer 配置缺失。"""

    error_code: str = ErrorCode.RETRIEVAL_NORMALIZER_CONFIG_MISSING


class NormalizerInvalidResponse(NormalizerError):
    """LLM normalizer 响应无法解析。"""

    error_code: str = ErrorCode.RETRIEVAL_NORMALIZER_INVALID_RESPONSE


# =============================================================================
# Prompt 模板
# =============================================================================

_NORMALIZER_PROMPT_TEMPLATE = (
    "你是一个案例检索查询标准化助手。"
    "请根据用户输入的问题，生成标准化检索文本和查询侧结构化画像。\n\n"
    "用户问题：{query_text}\n\n"
    "请以 JSON 格式返回结果，包含以下字段：\n"
    "- normalized_query_text: 标准化后的检索文本（用于向量搜索和语义重排），"
    "应简洁、准确、保留核心语义\n"
    "- query_structured_suggestions: 查询侧结构化画像，包含：\n"
    "  - suggested_problem_type: 建议问题类型\n"
    "  - suggested_root_cause_category: 建议根因分类\n"
    "  - suggested_applicable_scenes: 建议适用场景列表\n"
    "  - suggested_tags: 建议标签列表\n\n"
    "注意事项：\n"
    "- 只返回 JSON，不要有其他文字\n"
    "- 如果无法确定某个字段，返回 null 或空列表\n"
    "- normalized_query_text 不超过 200 字符"
)


# =============================================================================
# Internal Response Schema（用于 LLM 输出校验）
# =============================================================================


class _NormalizerOutput(BaseModel):
    """LLM normalizer 输出结构（内部校验用）。"""

    normalized_query_text: str = Field(..., description="标准化检索文本")
    query_structured_suggestions: dict[str, Any] = Field(
        ..., description="查询侧结构化画像"
    )

    model_config = {"extra": "forbid"}


# =============================================================================
# QueryNormalizer
# =============================================================================


class QueryNormalizer:
    """查询标准化服务。

    职责：
    1. 校验请求参数（query_text 非空、top_k 在范围内、filters 格式合法、weights 范围合法）
    2. 调用共享 LLMClient 执行单次 normalizer 外呼，传入 NormalizerLLMConfig
    3. 解析 LLM 返回的结构化结果，产出 NormalizedRetrievalQuery
    4. 失败时 fail closed（不兜底用原始 query_text），抛出可辨认异常

    使用共享 LLMClient（由 llm-case-enrichment 规格建立）与 NormalizerLLMConfig 配置。
    单次外呼同时产出 normalized_query_text 和 query_structured_suggestions。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config: NormalizerLLMConfig,
    ) -> None:
        """初始化 QueryNormalizer。

        Args:
            llm_client: 共享 LLMClient 实例。
            config: NormalizerLLMConfig 配置（由 llm-case-enrichment 规格定义）。
        """
        self._llm_client = llm_client
        self._config = config

    async def normalize(
        self,
        request: RetrievalRequest,
    ) -> NormalizedRetrievalQuery:
        """标准化用户查询。

        Args:
            request: 已通过 schema 校验的检索请求。

        Returns:
            NormalizedRetrievalQuery: 包含标准化检索文本、查询侧结构化画像、
                                      规范化过滤条件和有效业务权重。

        Raises:
            NormalizerTimeout: LLM 调用超时。
            NormalizerRateLimited: LLM 限流。
            NormalizerConfigMissing: 配置缺失。
            NormalizerInvalidResponse: LLM 响应无法解析。
        """
        # 1. 构建 LLM 请求
        prompt = _NORMALIZER_PROMPT_TEMPLATE.format(query_text=request.query_text)

        llm_request = LLMCompletionRequest(
            prompt=prompt,
            model_id=self._config.model_id,
            task_type=TaskType.CASE_ENRICHMENT,
            request_purpose=RequestPurpose.RETRIEVAL_QUERY_NORMALIZE,
            response_format=LLM_RESPONSE_FORMAT_JSON_OBJECT,
        )

        # 2. 执行 LLM 调用
        try:
            result = await self._llm_client.complete_json(llm_request)
        except LLMClientError as exc:
            raise self._map_llm_error(exc) from exc

        # 3. 解析 LLM 响应
        try:
            output_data = json.loads(result.content)
        except json.JSONDecodeError as exc:
            raise NormalizerInvalidResponse(
                f"LLM 响应不是有效的 JSON: {exc}"
            ) from exc

        # 4. Schema 校验
        try:
            output = _NormalizerOutput(**output_data)
        except ValidationError as exc:
            raise NormalizerInvalidResponse(
                f"LLM 响应 schema 校验失败: {exc}"
            ) from exc

        # 5. 组装查询侧结构化画像
        structured_suggestions = self._build_structured_suggestions(
            output.query_structured_suggestions
        )

        # 6. 规范化过滤条件
        applied_filters = self._normalize_filters(request.filters)

        # 7. 有效业务权重
        effective_weights = self._compute_effective_weights(request.business_weights)

        # 8. 返回标准化查询
        return NormalizedRetrievalQuery(
            normalized_query_text=output.normalized_query_text,
            query_structured_suggestions=structured_suggestions,
            applied_filters=applied_filters,
            effective_weights=effective_weights,
            top_k=request.top_k,
        )

    def _map_llm_error(self, exc: LLMClientError) -> NormalizerError:
        """将 LLMClientError 映射为 Normalizer 专用异常。"""
        error_code_map = {
            ErrorCode.LLM_TIMEOUT: NormalizerTimeout,
            ErrorCode.LLM_RATE_LIMITED: NormalizerRateLimited,
            ErrorCode.LLM_PRIVACY_CONFIG_MISSING: NormalizerConfigMissing,
            ErrorCode.LLM_PROVIDER_ERROR: NormalizerError,
            ErrorCode.LLM_INVALID_RESPONSE: NormalizerInvalidResponse,
        }

        exc_class = error_code_map.get(
            exc.error_code,
            NormalizerError,
        )
        return exc_class(exc.message)

    def _build_structured_suggestions(
        self,
        raw: dict[str, Any],
    ) -> QueryStructuredSuggestions:
        """从 LLM 原始输出构建 QueryStructuredSuggestions。"""
        return QueryStructuredSuggestions(
            suggested_problem_type=raw.get("suggested_problem_type"),
            suggested_root_cause_category=raw.get("suggested_root_cause_category"),
            suggested_applicable_scenes=raw.get("suggested_applicable_scenes"),
            suggested_tags=raw.get("suggested_tags"),
        )

    def _normalize_filters(
        self,
        filters: RetrievalFilters | None,
    ) -> dict[str, Any]:
        """将 RetrievalFilters 规范化为字典。"""
        if filters is None:
            return {}

        result: dict[str, Any] = {}
        if filters.brand_id is not None:
            result["brand_id"] = filters.brand_id
        if filters.store_id is not None:
            result["store_id"] = filters.store_id
        if filters.problem_type is not None:
            result["problem_type"] = filters.problem_type
        if filters.tags is not None:
            result["tags"] = filters.tags
        if filters.case_status is not None:
            result["case_status"] = filters.case_status
        if filters.created_at_from is not None:
            result["created_at_from"] = filters.created_at_from.isoformat()
        if filters.created_at_to is not None:
            result["created_at_to"] = filters.created_at_to.isoformat()

        return result

    def _compute_effective_weights(
        self,
        weights: BusinessWeights | None,
    ) -> dict[str, float]:
        """计算有效业务权重（使用默认或自定义）。"""
        if weights is None:
            # 使用默认权重
            weights = BusinessWeights()

        return {
            "business_type": weights.business_type_weight,
            "store_tier": weights.store_tier_weight,
            "brand_affinity": weights.brand_affinity_weight,
            "recency": weights.recency_weight,
        }
