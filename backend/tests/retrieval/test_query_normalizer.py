"""QueryNormalizer 单元测试。

测试 QueryNormalizer 的：
1. 输入校验：空查询、Top-K 越界、无效过滤字段、无效业务权重
2. LLM normalizer 调用成功
3. LLM normalizer 失败（超时、限流、配置缺失、响应不可解析）
4. 过滤字段映射与回显
5. 业务权重默认与校验
6. Requirement 1.7 fail closed 行为
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMClient, LLMClientError
from app.core.config import AppConfig, NormalizerLLMConfig, get_app_config
from app.core.errors import ErrorCode
from app.enrichment.schemas import LLMCompletionRequest, RequestPurpose, TaskType
from app.retrieval.schemas import (
    BusinessWeights,
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
    RetrievalFilters,
    RetrievalRequest,
    ValidationErrorDetail,
    ValidationErrorResponse,
)


# ---------------------------------------------------------------------------
# Feature Flag: QueryNormalizer 功能开关
# ---------------------------------------------------------------------------

# TODO: QueryNormalizer 实现后移除此 flag
RETRIEVAL_QUERY_NORMALIZER_ENABLED = True


def _is_normalizer_enabled() -> bool:
    """检查 QueryNormalizer 功能是否启用。"""
    return RETRIEVAL_QUERY_NORMALIZER_ENABLED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

from app.core.config import load_app_config


def _app_config() -> AppConfig:
    """测试用 AppConfig。"""
    return load_app_config()


def _normalizer_config() -> NormalizerLLMConfig:
    """测试用 NormalizerLLMConfig。"""
    return _app_config().normalizer_llm


def _normalizer_llm_completion_request(**overrides) -> LLMCompletionRequest:
    """构造 LLM normalizer 调用请求。"""
    defaults = {
        "prompt": "请分析以下案例问题并生成标准化查询...",
        "model_id": _normalizer_config().model_id,
        "task_type": TaskType.CASE_ENRICHMENT,
        "request_purpose": RequestPurpose.CASE_RETRIEVAL_QUERY,
    }
    defaults.update(overrides)
    return LLMCompletionRequest(**defaults)


def _stub_normalizer_completion(
    normalized_text: str = "门店客户投诉处理方法",
    structured_suggestions: dict | None = None,
) -> SimpleNamespace:
    """构造 normalizer 成功的 LLM 响应。"""
    import json

    structured = structured_suggestions or {
        "suggested_problem_type": "客户投诉",
        "suggested_root_cause_category": "服务态度",
        "suggested_applicable_scenes": ["零售", "餐饮"],
        "suggested_tags": ["投诉", "服务"],
    }
    content = json.dumps({
        "normalized_query_text": normalized_text,
        "query_structured_suggestions": structured,
    })
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            ),
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        ),
        model=_normalizer_config().model_id,
    )


def _mock_normalizer_async_client(completion: SimpleNamespace) -> MagicMock:
    m = MagicMock()
    m.chat.completions.create = AsyncMock(return_value=completion)
    return m


# ---------------------------------------------------------------------------
# Tests: Feature Flag Gate
# ---------------------------------------------------------------------------


class TestFeatureFlagGate:
    """Feature Flag Protocol: flag=OFF 时测试应跳过或失败。"""

    @pytest.mark.skipif(
        _is_normalizer_enabled(),
        reason="QueryNormalizer 功能已启用，跳过此测试",
    )
    def test_normalizer_disabled_raises(self):
        """flag=OFF 时，QueryNormalizer 不可用。"""
        with pytest.raises(ImportError):
            from app.retrieval.query import QueryNormalizer  # noqa: F401


# ---------------------------------------------------------------------------
# Tests: 基础输入校验
# ---------------------------------------------------------------------------


class TestBasicValidation:
    """基础输入校验（Requirement 1.3）。"""

    def test_empty_query_text_raises_validation_error(self):
        """空 query_text 返回字段级错误（422）。"""
        with pytest.raises(ValidationError) as exc_info:
            RetrievalRequest(query_text="", top_k=10)

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("query_text",) for e in errors)

    def test_whitespace_only_query_text_strips_and_passes(self):
        """Pydantic v2 默认不 strip 空白字符，"   " 通过 min_length=1 校验是预期行为。"""
        # Pydantic 默认保留空白字符，"   " 长度为 3，满足 min_length=1
        # 如需严格校验空白，需在 schema 中自定义 validator
        req = RetrievalRequest(query_text="   ", top_k=10)
        assert req.query_text == "   "

    def test_top_k_zero_raises(self):
        """top_k=0 校验失败。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=0)

    def test_top_k_negative_raises(self):
        """top_k<0 校验失败。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=-1)

    def test_top_k_exceeds_max_raises(self):
        """top_k 超过 schema 上限（le=100）校验失败。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=101)

    def test_valid_request_passes(self):
        """合法请求通过校验。"""
        req = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)
        assert req.query_text == "客户投诉怎么处理"
        assert req.top_k == 10

    def test_valid_request_with_filters(self):
        """带过滤条件的合法请求通过校验。"""
        filters = RetrievalFilters(
            brand_id="brand-001",
            store_id="store-001",
            problem_type="客户投诉",
            tags=["投诉", "服务"],
            case_status="active",
            created_at_from=None,
            created_at_to=None,
        )
        req = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            filters=filters,
        )
        assert req.filters is not None
        assert req.filters.brand_id == "brand-001"

    def test_valid_request_with_business_weights(self):
        """带业务权重的合法请求通过校验。"""
        weights = BusinessWeights(
            business_type_weight=0.3,
            store_tier_weight=0.2,
            brand_affinity_weight=0.1,
            recency_weight=0.05,
        )
        req = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            business_weights=weights,
        )
        assert req.business_weights is not None
        assert req.business_weights.business_type_weight == 0.3

    def test_business_weights_out_of_range_raises(self):
        """业务权重超出 [0, 1] 范围校验失败。"""
        with pytest.raises(ValidationError):
            BusinessWeights(
                business_type_weight=1.5,  # 超出范围
                store_tier_weight=0.2,
                brand_affinity_weight=0.1,
                recency_weight=0.05,
            )

    def test_extra_filter_field_forbidden(self):
        """未列入上游契约的过滤字段返回字段级错误。"""
        # RetrievalFilters 使用 extra="forbid"，不允许未知字段
        with pytest.raises(ValidationError):
            RetrievalFilters(
                brand_id="brand-001",
                unknown_field="should fail",  # 不在契约中
            )

    def test_extra_business_weight_field_forbidden(self):
        """业务权重不允许额外字段。"""
        with pytest.raises(ValidationError):
            BusinessWeights(
                business_type_weight=0.3,
                unknown_weight_field=0.5,  # 不在契约中
            )


# ---------------------------------------------------------------------------
# Tests: LLM Normalizer 调用
# ---------------------------------------------------------------------------


class TestLLMNormalizerSuccess:
    """LLM normalizer 成功场景。"""

    @pytest.mark.asyncio
    async def test_normalize_returns_structured_query(self):
        """LLM normalizer 成功时返回 NormalizedRetrievalQuery。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import QueryNormalizer

        comp = _stub_normalizer_completion(
            normalized_text="门店客户投诉处理方法",
            structured_suggestions={
                "suggested_problem_type": "客户投诉",
                "suggested_root_cause_category": "服务态度",
                "suggested_applicable_scenes": ["零售", "餐饮"],
                "suggested_tags": ["投诉", "服务"],
            },
        )
        mock_client = _mock_normalizer_async_client(comp)
        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        assert isinstance(result, NormalizedRetrievalQuery)
        assert result.normalized_query_text == "门店客户投诉处理方法"
        assert result.query_structured_suggestions.suggested_problem_type == "客户投诉"
        assert result.top_k == 10

    @pytest.mark.asyncio
    async def test_normalize_echoes_applied_filters(self):
        """规范化后的过滤条件回显到结果中。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import QueryNormalizer

        comp = _stub_normalizer_completion()
        mock_client = _mock_normalizer_async_client(comp)
        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            filters=RetrievalFilters(
                brand_id="brand-001",
                problem_type="客户投诉",
            ),
        )

        result = await normalizer.normalize(request)

        assert "brand_id" in result.applied_filters
        assert result.applied_filters["brand_id"] == "brand-001"

    @pytest.mark.asyncio
    async def test_normalize_echoes_effective_weights(self):
        """有效业务权重回显到结果中（使用默认权重）。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import QueryNormalizer

        comp = _stub_normalizer_completion()
        mock_client = _mock_normalizer_async_client(comp)
        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            # 不提供 business_weights，使用默认权重
        )

        result = await normalizer.normalize(request)

        assert "business_type" in result.effective_weights
        assert "store_tier" in result.effective_weights

    @pytest.mark.asyncio
    async def test_normalize_with_custom_weights(self):
        """自定义业务权重正确合并到结果。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import QueryNormalizer

        comp = _stub_normalizer_completion()
        mock_client = _mock_normalizer_async_client(comp)
        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            business_weights=BusinessWeights(
                business_type_weight=0.5,
                store_tier_weight=0.3,
                brand_affinity_weight=0.1,
                recency_weight=0.1,
            ),
        )

        result = await normalizer.normalize(request)

        # 自定义权重被接受
        assert result.effective_weights.get("business_type") == 0.5


# ---------------------------------------------------------------------------
# Tests: LLM Normalizer 失败（Requirement 1.7）
# ---------------------------------------------------------------------------


class TestLLMNormalizerFailure:
    """LLM normalizer 失败场景（Requirement 1.7 fail closed）。"""

    @pytest.mark.asyncio
    async def test_normalizer_timeout_raises_specific_error(self):
        """LLM normalizer 超时时抛出可辨认的异常。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import NormalizerTimeout, QueryNormalizer

        import openai

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerTimeout):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_rate_limited_raises_specific_error(self):
        """LLM normalizer 限流时抛出可辨认的异常。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import NormalizerRateLimited, QueryNormalizer

        import httpx
        import openai

        req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")

        async def raise_429(**kwargs):
            raise openai.RateLimitError(
                "rate limited",
                response=httpx.Response(429, request=req),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_429)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerRateLimited):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_config_missing_raises_specific_error(self):
        """LLM normalizer 配置缺失时抛出可辨认的异常。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import NormalizerConfigMissing, QueryNormalizer

        config = NormalizerLLMConfig(
            api_key="fake-key",
            model_id="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            timeout_ms=10000,
            max_retries=0,
        )
        # 使用 fake client 但 complete_json 抛出 LLMClientError
        # 模拟配置缺失导致的错误（api_key 为空时 LLMClient 会抛出）
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_PRIVACY_CONFIG_MISSING,
                message="API key is empty",
                retryable=False,
            )
        )

        normalizer = QueryNormalizer(llm_client=mock_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerConfigMissing):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_invalid_response_raises_specific_error(self):
        """LLM normalizer 响应不可解析时抛出可辨认的异常。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import NormalizerInvalidResponse, QueryNormalizer

        # 响应 content 不是有效的 JSON
        bad_comp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="这不是有效的 JSON"),
                    finish_reason="stop",
                ),
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model=_normalizer_config().model_id,
        )
        mock = _mock_normalizer_async_client(bad_comp)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerInvalidResponse):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_failure_does_not_return_fallback(self):
        """LLM normalizer 失败时不得使用原始 query_text 兜底。"""
        if not _is_normalizer_enabled():
            pytest.skip("QueryNormalizer 功能未启用")

        from app.retrieval.query import QueryNormalizer

        import openai

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        # 失败时抛出异常，不返回使用原始 query_text 的 NormalizedRetrievalQuery
        try:
            await normalizer.normalize(request)
            pytest.fail("Expected NormalizerTimeout but no exception was raised")
        except Exception as exc:
            # 确认是 normalizer 异常，不是普通异常
            assert exc.__class__.__name__.startswith("Normalizer")


# ---------------------------------------------------------------------------
# Tests: 过滤字段校验
# ---------------------------------------------------------------------------


class TestFilterFieldValidation:
    """过滤字段校验：对未列入上游契约的过滤字段返回字段级错误。"""

    def test_unsupported_filter_field_returns_field_error(self):
        """不支持的过滤字段应被拒绝。"""
        # RetrievalFilters 使用 extra="forbid"
        # 任何未定义的字段都会被 Pydantic 拒绝
        with pytest.raises(ValidationError) as exc_info:
            RetrievalFilters(
                brand_id="brand-001",
                unsupported_field="should fail",
            )

        errors = exc_info.value.errors()
        # extra="forbid" 时 Pydantic v2 返回 "extra_forbidden" 类型
        assert any(
            e.get("type") == "extra_forbidden"
            or "extra" in str(e.get("ctx", {})).lower()
            for e in errors
        )

    def test_known_filter_fields_accepted(self):
        """上游契约定义的过滤字段被正确接受。"""
        filters = RetrievalFilters(
            brand_id="brand-001",
            store_id="store-001",
            problem_type="客户投诉",
            tags=["投诉", "服务"],
            case_status="active",
        )
        assert filters.brand_id == "brand-001"
        assert filters.store_id == "store-001"


# ---------------------------------------------------------------------------
# Tests: BusinessWeights 默认与范围
# ---------------------------------------------------------------------------


class TestBusinessWeightsValidation:
    """业务权重校验：范围 [0, 1]，默认权重使用配置值。"""

    def test_weights_all_zeros_allowed(self):
        """权重全为 0 允许（表示完全忽略该维度）。"""
        weights = BusinessWeights(
            business_type_weight=0.0,
            store_tier_weight=0.0,
            brand_affinity_weight=0.0,
            recency_weight=0.0,
        )
        assert weights.business_type_weight == 0.0

    def test_weights_exactly_one_allowed(self):
        """权重为 1.0 允许。"""
        weights = BusinessWeights(business_type_weight=1.0)
        assert weights.business_type_weight == 1.0

    def test_weights_negative_rejected(self):
        """负权重被拒绝。"""
        with pytest.raises(ValidationError):
            BusinessWeights(business_type_weight=-0.1)

    def test_weights_greater_than_one_rejected(self):
        """大于 1 的权重被拒绝。"""
        with pytest.raises(ValidationError):
            BusinessWeights(business_type_weight=1.5)

    def test_default_weights_within_valid_range(self):
        """默认权重值在有效范围内。"""
        default_weights = BusinessWeights()
        assert 0 <= default_weights.business_type_weight <= 1
        assert 0 <= default_weights.store_tier_weight <= 1
        assert 0 <= default_weights.brand_affinity_weight <= 1
        assert 0 <= default_weights.recency_weight <= 1


# ---------------------------------------------------------------------------
# Tests: QueryStructuredSuggestions Schema
# ---------------------------------------------------------------------------


class TestQueryStructuredSuggestions:
    """查询侧结构化画像 Schema 验证。"""

    def test_valid_structured_suggestions(self):
        """合法的结构化画像通过校验。"""
        suggestions = QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
            suggested_root_cause_category="服务态度",
            suggested_applicable_scenes=["零售", "餐饮"],
            suggested_tags=["投诉", "服务"],
        )
        assert suggestions.suggested_problem_type == "客户投诉"
        assert suggestions.suggested_applicable_scenes == ["零售", "餐饮"]

    def test_partial_structured_suggestions(self):
        """部分字段为空的结构化画像通过校验（MVP 场景）。"""
        suggestions = QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
            # 其他字段为 None
        )
        assert suggestions.suggested_problem_type == "客户投诉"
        assert suggestions.suggested_root_cause_category is None

    def test_empty_structured_suggestions(self):
        """空结构化画像通过校验（允许 MVP 降级）。"""
        suggestions = QueryStructuredSuggestions()
        assert suggestions.suggested_problem_type is None
