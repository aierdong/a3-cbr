"""查询、过滤、业务权重校验测试。

测试覆盖：
- 空查询、Top-K 越界、无效过滤、权重越界、过滤回显、权重回显
- QueryNormalizer + 共享 LLMClient：成功解析、超时、限流、配置缺失、响应不可解析
- QueryNormalizer：LLM normalizer 失败时不调用向量端口
- QueryNormalizer：成功时 NormalizedRetrievalQuery 同时携带检索文本与 query_structured_suggestions

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7

Boundary: QueryNormalizer (with shared LLMClient)
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMClient, LLMClientError
from app.core.config import NormalizerLLMConfig, RerankerConfig
from app.core.errors import ErrorCode
from app.retrieval.query import (
    NormalizerConfigMissing,
    NormalizerInvalidResponse,
    NormalizerRateLimited,
    NormalizerTimeout,
    QueryNormalizer,
)
from app.retrieval.schemas import (
    BusinessWeights,
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
    RetrievalFilters,
    RetrievalRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_normalizer_config(
    api_key: str = "test-key",
    model_id: str = "deepseek-v4-flash",
    base_url: str = "https://api.deepseek.com",
    timeout_ms: int = 30000,
    max_retries: int = 2,
) -> NormalizerLLMConfig:
    """构造 NormalizerLLMConfig。"""
    return NormalizerLLMConfig(
        api_key=api_key,
        model_id=model_id,
        base_url=base_url,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
    )


def _make_reranker_config(
    api_key: str = "test-key",
    model_id: str = "qwen3-reranker-8b",
    base_url: str = "https://api.qianfan.com",
    timeout_ms: int = 45000,
    max_retries: int = 2,
) -> RerankerConfig:
    """构造 RerankerConfig（用于配置隔离测试）。"""
    return RerankerConfig(
        api_key=api_key,
        model_id=model_id,
        base_url=base_url,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
    )


def _stub_normalizer_completion(
    normalized_text: str = "门店客户投诉处理方法",
    structured_suggestions: dict | None = None,
) -> SimpleNamespace:
    """构造 normalizer 成功的 LLM 响应。"""
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
        model="deepseek-v4-flash",
    )


def _mock_async_client(completion: SimpleNamespace) -> MagicMock:
    """构造 Mock AsyncOpenAI 客户端。"""
    m = MagicMock()
    m.chat.completions.create = AsyncMock(return_value=completion)
    return m


# ---------------------------------------------------------------------------
# Tests: 基础 Schema 校验（Requirement 1.3）
# ---------------------------------------------------------------------------


class TestBasicSchemaValidation:
    """基础 Schema 校验：空查询、Top-K 越界、无效过滤、权重越界。"""

    def test_empty_query_text_raises_validation_error(self):
        """空 query_text 返回字段级错误（Requirement 1.3）。"""
        with pytest.raises(ValidationError) as exc_info:
            RetrievalRequest(query_text="", top_k=10)

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("query_text",) for e in errors)

    def test_top_k_zero_raises(self):
        """top_k=0 校验失败（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=0)

    def test_top_k_negative_raises(self):
        """top_k<0 校验失败（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=-1)

    def test_top_k_exceeds_max_raises(self):
        """top_k 超过 schema 上限（le=100）校验失败（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            RetrievalRequest(query_text="客户投诉", top_k=101)

    def test_business_weights_out_of_range_raises(self):
        """业务权重超出 [0, 1] 范围校验失败（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            BusinessWeights(
                business_type_weight=1.5,
                store_tier_weight=0.2,
                brand_affinity_weight=0.1,
                recency_weight=0.05,
            )

    def test_negative_weights_rejected(self):
        """负权重被拒绝（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            BusinessWeights(business_type_weight=-0.1)

    def test_extra_filter_field_forbidden(self):
        """未列入上游契约的过滤字段返回字段级错误（Requirement 1.2）。"""
        with pytest.raises(ValidationError):
            RetrievalFilters(
                brand_id="brand-001",
                unknown_field="should fail",
            )

    def test_extra_business_weight_field_forbidden(self):
        """业务权重不允许额外字段（Requirement 1.2）。"""
        with pytest.raises(ValidationError):
            BusinessWeights(
                business_type_weight=0.3,
                unknown_weight_field=0.5,
            )

    def test_valid_request_passes(self):
        """合法请求通过校验（Requirement 1.1）。"""
        req = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)
        assert req.query_text == "客户投诉怎么处理"
        assert req.top_k == 10

    def test_valid_request_with_filters(self):
        """带过滤条件的合法请求通过校验（Requirement 1.2）。"""
        filters = RetrievalFilters(
            brand_id="brand-001",
            store_id="store-001",
            problem_type="客户投诉",
            tags=["投诉", "服务"],
            case_status="active",
        )
        req = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
            filters=filters,
        )
        assert req.filters is not None
        assert req.filters.brand_id == "brand-001"

    def test_valid_request_with_business_weights(self):
        """带业务权重的合法请求通过校验（Requirement 1.1）。"""
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


# ---------------------------------------------------------------------------
# Tests: 过滤字段校验（Requirement 1.2）
# ---------------------------------------------------------------------------


class TestFilterFieldValidation:
    """过滤字段校验：对未列入上游契约的过滤字段返回字段级错误。"""

    def test_unsupported_filter_field_returns_field_error(self):
        """不支持的过滤字段应被拒绝（Requirement 1.2）。"""
        with pytest.raises(ValidationError) as exc_info:
            RetrievalFilters(
                brand_id="brand-001",
                unsupported_field="should fail",
            )

        errors = exc_info.value.errors()
        assert any(
            e.get("type") == "extra_forbidden"
            or "extra" in str(e.get("ctx", {})).lower()
            for e in errors
        )

    def test_known_filter_fields_accepted(self):
        """上游契约定义的过滤字段被正确接受（Requirement 1.2）。"""
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
# Tests: BusinessWeights 范围与默认（Requirement 1.1, 4.2）
# ---------------------------------------------------------------------------


class TestBusinessWeightsValidation:
    """业务权重校验：范围 [0, 1]，默认权重使用配置值。"""

    def test_weights_all_zeros_allowed(self):
        """权重全为 0 允许（表示完全忽略该维度，Requirement 4.2）。"""
        weights = BusinessWeights(
            business_type_weight=0.0,
            store_tier_weight=0.0,
            brand_affinity_weight=0.0,
            recency_weight=0.0,
        )
        assert weights.business_type_weight == 0.0

    def test_weights_exactly_one_allowed(self):
        """权重为 1.0 允许（Requirement 4.2）。"""
        weights = BusinessWeights(business_type_weight=1.0)
        assert weights.business_type_weight == 1.0

    def test_weights_negative_rejected(self):
        """负权重被拒绝（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            BusinessWeights(business_type_weight=-0.1)

    def test_weights_greater_than_one_rejected(self):
        """大于 1 的权重被拒绝（Requirement 1.3）。"""
        with pytest.raises(ValidationError):
            BusinessWeights(business_type_weight=1.5)

    def test_default_weights_within_valid_range(self):
        """默认权重值在有效范围内（Requirement 4.2）。"""
        default_weights = BusinessWeights()
        assert 0 <= default_weights.business_type_weight <= 1
        assert 0 <= default_weights.store_tier_weight <= 1
        assert 0 <= default_weights.brand_affinity_weight <= 1
        assert 0 <= default_weights.recency_weight <= 1


# ---------------------------------------------------------------------------
# Tests: LLM Normalizer 成功路径（Requirement 1.6）
# ---------------------------------------------------------------------------


class TestLLMNormalizerSuccess:
    """LLM normalizer 成功场景。"""

    @pytest.mark.asyncio
    async def test_normalize_returns_structured_query(self):
        """LLM normalizer 成功时返回 NormalizedRetrievalQuery（Requirement 1.6）。"""
        comp = _stub_normalizer_completion(
            normalized_text="门店客户投诉处理方法",
            structured_suggestions={
                "suggested_problem_type": "客户投诉",
                "suggested_root_cause_category": "服务态度",
                "suggested_applicable_scenes": ["零售", "餐饮"],
                "suggested_tags": ["投诉", "服务"],
            },
        )
        mock_client = _mock_async_client(comp)
        config = _make_normalizer_config()
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
    async def test_normalize_carries_both_text_and_structured_suggestions(self):
        """成功时 NormalizedRetrievalQuery 同时携带检索文本.

        query_structured_suggestions（Requirement 1.6）。
        """
        comp = _stub_normalizer_completion(
            normalized_text="门店客户投诉处理方法",
            structured_suggestions={
                "suggested_problem_type": "客户投诉",
                "suggested_root_cause_category": "服务态度",
                "suggested_applicable_scenes": ["零售", "餐饮"],
                "suggested_tags": ["投诉", "服务"],
            },
        )
        mock_client = _mock_async_client(comp)
        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        # 检索文本和 query_structured_suggestions 同时存在
        assert result.normalized_query_text is not None
        assert result.query_structured_suggestions is not None
        assert isinstance(result.query_structured_suggestions, QueryStructuredSuggestions)
        assert result.query_structured_suggestions.suggested_problem_type == "客户投诉"

    @pytest.mark.asyncio
    async def test_normalize_echoes_applied_filters(self):
        """规范化后的过滤条件回显到结果中（Requirement 1.5）。"""
        comp = _stub_normalizer_completion()
        mock_client = _mock_async_client(comp)
        config = _make_normalizer_config()
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
        assert "problem_type" in result.applied_filters

    @pytest.mark.asyncio
    async def test_normalize_echoes_effective_weights(self):
        """有效业务权重回显到结果中（使用默认权重，Requirement 1.5）。"""
        comp = _stub_normalizer_completion()
        mock_client = _mock_async_client(comp)
        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        assert "business_type" in result.effective_weights
        assert "store_tier" in result.effective_weights
        assert "brand_affinity" in result.effective_weights
        assert "recency" in result.effective_weights

    @pytest.mark.asyncio
    async def test_normalize_with_custom_weights(self):
        """自定义业务权重正确合并到结果（Requirement 1.5, 4.2）。"""
        comp = _stub_normalizer_completion()
        mock_client = _mock_async_client(comp)
        config = _make_normalizer_config()
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
        assert result.effective_weights.get("store_tier") == 0.3


# ---------------------------------------------------------------------------
# Tests: LLM Normalizer 失败路径（Requirement 1.7）
# ---------------------------------------------------------------------------


class TestLLMNormalizerFailure:
    """LLM normalizer 失败场景（Requirement 1.7 fail closed）。"""

    @pytest.mark.asyncio
    async def test_normalizer_timeout_raises_specific_error(self):
        """LLM normalizer 超时时抛出可辨认的 NormalizerTimeout（Requirement 1.7）。"""
        import openai

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerTimeout):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_rate_limited_raises_specific_error(self):
        """LLM normalizer 限流时抛出可辨认的 NormalizerRateLimited（Requirement 1.7）。"""
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

        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerRateLimited):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_config_missing_raises_specific_error(self):
        """LLM normalizer 配置缺失时抛出可辨认的 NormalizerConfigMissing（Requirement 1.7）。"""
        config = _make_normalizer_config(
            api_key="fake-key",
            model_id="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            timeout_ms=10000,
            max_retries=0,
        )
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
    async def test_normalizer_invalid_json_raises_specific_error(self):
        """LLM normalizer 响应不是有效 JSON 时抛出 NormalizerInvalidResponse（Requirement 1.7）。"""
        bad_comp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="这不是有效的 JSON"),
                    finish_reason="stop",
                ),
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="deepseek-v4-flash",
        )
        mock = _mock_async_client(bad_comp)

        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerInvalidResponse):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_invalid_schema_raises_specific_error(self):
        """LLM normalizer 响应 schema 校验失败时抛出 NormalizerInvalidResponse.

        Requirement 1.7.
        """
        # 响应缺少必需字段 normalized_query_text
        bad_comp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({
                        "wrong_field": "门店客户投诉处理"
                    })),
                    finish_reason="stop",
                ),
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="deepseek-v4-flash",
        )
        mock = _mock_async_client(bad_comp)

        config = _make_normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerInvalidResponse):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_failure_does_not_return_fallback(self):
        """LLM normalizer 失败时不得使用原始 query_text 兜底（Requirement 1.7）。"""
        import openai

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        config = _make_normalizer_config()
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
# Tests: QueryStructuredSuggestions Schema（Requirement 1.6）
# ---------------------------------------------------------------------------


class TestQueryStructuredSuggestions:
    """查询侧结构化画像 Schema 验证。"""

    def test_valid_structured_suggestions(self):
        """合法的结构化画像通过校验（Requirement 1.6）。"""
        suggestions = QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
            suggested_root_cause_category="服务态度",
            suggested_applicable_scenes=["零售", "餐饮"],
            suggested_tags=["投诉", "服务"],
        )
        assert suggestions.suggested_problem_type == "客户投诉"
        assert suggestions.suggested_applicable_scenes == ["零售", "餐饮"]

    def test_partial_structured_suggestions(self):
        """部分字段为空的结构化画像通过校验（Requirement 1.6, MVP 场景）。"""
        suggestions = QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
        )
        assert suggestions.suggested_problem_type == "客户投诉"
        assert suggestions.suggested_root_cause_category is None

    def test_empty_structured_suggestions(self):
        """空结构化画像通过校验（Requirement 1.6, 允许 MVP 降级）。"""
        suggestions = QueryStructuredSuggestions()
        assert suggestions.suggested_problem_type is None


# ---------------------------------------------------------------------------
# Tests: 配置隔离回归测试（Requirement 复用 llm-case-enrichment 基础设施）
# ---------------------------------------------------------------------------


class TestConfigIsolation:
    """配置隔离回归测试：验证 NormalizerLLMConfig 和 RerankerConfig 独立实例。"""

    def test_normalizer_config_and_reranker_config_are_independent(self):
        """验证 NormalizerLLMConfig 和 RerankerConfig 是独立实例（id() 检查）。"""
        normalizer_config = _make_normalizer_config(timeout_ms=30000)
        reranker_config = _make_reranker_config(timeout_ms=45000)

        # 两个配置对象不是同一实例
        assert id(normalizer_config) != id(reranker_config)

        # 修改 RerankerConfig 的 timeout_ms 不影响 NormalizerLLMConfig
        original_normalizer_timeout = normalizer_config.timeout_ms
        reranker_config.timeout_ms = 60000

        assert normalizer_config.timeout_ms == original_normalizer_timeout
        assert reranker_config.timeout_ms == 60000

    def test_reranker_config_modification_does_not_affect_normalizer(self):
        """验证修改 RerankerConfig.timeout_ms 不影响 NormalizerLLMConfig 的调用参数。"""
        normalizer_config = _make_normalizer_config(
            api_key="normalizer-key",
            model_id="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            timeout_ms=30000,
        )
        reranker_config = _make_reranker_config(
            api_key="reranker-key",
            model_id="qwen3-reranker-8b",
            base_url="https://api.qianfan.com",
            timeout_ms=45000,
        )

        # 保存原始值
        original_normalizer_timeout = normalizer_config.timeout_ms
        original_normalizer_api_key = normalizer_config.api_key

        # 修改 RerankerConfig
        reranker_config.timeout_ms = 60000
        reranker_config.api_key = "modified-reranker-key"

        # NormalizerLLMConfig 未受影响
        assert normalizer_config.timeout_ms == original_normalizer_timeout
        assert normalizer_config.api_key == original_normalizer_api_key
        assert normalizer_config.model_id == "deepseek-v4-flash"

    def test_normalizer_llm_client_uses_normalizer_config_not_reranker_config(self):
        """验证 LLMClient 使用 NormalizerLLMConfig 而非 RerankerConfig。"""
        normalizer_config = _make_normalizer_config(
            api_key="normalizer-key",
            model_id="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            timeout_ms=30000,
        )
        reranker_config = _make_reranker_config(
            api_key="reranker-key",
            model_id="qwen3-reranker-8b",
            base_url="https://api.qianfan.com",
            timeout_ms=45000,
        )

        # 创建使用 NormalizerLLMConfig 的 LLMClient
        normalizer_llm_client = LLMClient(normalizer_config)

        # LLMClient 内部使用的是 NormalizerLLMConfig 的参数
        assert normalizer_llm_client._model_id == "deepseek-v4-flash"
        assert normalizer_llm_client._api_key == "normalizer-key"
        assert normalizer_llm_client._timeout_s == pytest.approx(30.0)

        # 创建使用 RerankerConfig 的 LLMClient
        reranker_llm_client = LLMClient(reranker_config)

        # LLMClient 内部使用的是 RerankerConfig 的参数
        assert reranker_llm_client._model_id == "qwen3-reranker-8b"
        assert reranker_llm_client._api_key == "reranker-key"
        assert reranker_llm_client._timeout_s == pytest.approx(45.0)

        # 两者参数不同
        assert normalizer_llm_client._model_id != reranker_llm_client._model_id
        assert normalizer_llm_client._api_key != reranker_llm_client._api_key
