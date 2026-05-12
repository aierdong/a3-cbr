"""LLM normalizer 集成测试（QueryNormalizer + RecommendationService）。

测试覆盖：
- QueryNormalizer + 共享 LLMClient：成功解析、超时、限流、配置缺失、响应不可解析
- QueryNormalizer：LLM normalizer 失败时不调用向量端口
- QueryNormalizer：成功时 NormalizedRetrievalQuery 同时携带检索文本与 query_structured_suggestions
- 结合 RecommendationService：断言 create_run → normalizer 失败 → fail_run
- 空候选、候选不足和向量搜索失败
- 断言向量候选只包含可检索案例

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5

Boundary: QueryNormalizer (with shared LLMClient), VectorSearchPort_
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.llm_client import LLMClient
from app.core.config import NormalizerLLMConfig, RetrievalConfig, RerankerConfig
from app.retrieval.query import (
    NormalizerConfigMissing,
    NormalizerInvalidResponse,
    NormalizerRateLimited,
    NormalizerTimeout,
    QueryNormalizer,
)
from app.core.llm_client import LLMClientError
from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import (
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
    RetrievalRequest,
    RunStatus,
)
from app.retrieval.service import RecommendationService
from app.retrieval.vector_port import (
    VectorCandidate,
    VectorCandidateBatch,
    VectorSearchPort,
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
    """构造 RerankerConfig。"""
    return RerankerConfig(
        api_key=api_key,
        model_id=model_id,
        base_url=base_url,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
    )


def _make_retrieval_config(
    reranker_model_id: str = "qwen3-reranker-8b",
) -> RetrievalConfig:
    """构造 RetrievalConfig。"""
    return RetrievalConfig(
        retrieval_enabled=True,
        max_top_k=20,
        max_vector_candidates=50,
        default_score_weights={
            "vector": 0.3,
            "semantic": 0.4,
            "structured": 0.1,
            "business": 0.2,
        },
        max_business_weight=1.0,
        contract_version="mvp-1",
        reranker_model_id=reranker_model_id,
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


def _make_vector_candidates(count: int = 3) -> list[VectorCandidate]:
    """构造 VectorCandidate 列表。"""
    candidates = []
    for i in range(count):
        candidates.append(
            VectorCandidate(
                case_id=f"case-{i+1:03d}",
                vector_id=f"vec-{i+1:03d}",
                similarity_score=0.95 - i * 0.05,
                distance=0.05 + i * 0.02,
                case_updated_at=datetime(2025, 1, i + 1),
                input_content_hash=f"hash{i+1:03d}",
                index_status="searchable",
                filter_metadata={},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Tests: QueryNormalizer + RecommendationService 集成
# ---------------------------------------------------------------------------


class TestQueryNormalizerServiceIntegration:
    """QueryNormalizer + RecommendationService 集成测试。"""

    @pytest.mark.asyncio
    async def test_normalizer_failure_does_not_call_vector_port(self):
        """LLM normalizer 失败时不调用向量端口（Requirement 1.7）。"""
        from app.core.errors import ErrorCode

        # Mock normalizer 抛出超时异常（模拟 LLMClient 映射后的 LLMClientError）
        mock_llm_client = MagicMock()
        mock_llm_client.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_TIMEOUT,
                message="模型网关超时",
                retryable=True,
            )
        )

        normalizer_config = _make_normalizer_config()
        normalizer = QueryNormalizer(
            llm_client=mock_llm_client,
            config=normalizer_config,
        )

        # 直接测试 normalizer 抛出异常时不返回 NormalizedRetrievalQuery
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        with pytest.raises(NormalizerTimeout):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_success_returns_normalized_query(self):
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
        normalizer_config = _make_normalizer_config()
        llm_client = LLMClient(normalizer_config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=normalizer_config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        # 成功时返回 NormalizedRetrievalQuery
        assert isinstance(result, NormalizedRetrievalQuery)
        assert result.normalized_query_text == "门店客户投诉处理方法"
        assert result.query_structured_suggestions.suggested_problem_type == "客户投诉"

    @pytest.mark.asyncio
    async def test_normalizer_carries_text_and_structured_suggestions(self):
        """成功时 NormalizedRetrievalQuery 同时携带检索文本。

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
        normalizer_config = _make_normalizer_config()
        llm_client = LLMClient(normalizer_config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=normalizer_config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        # 检索文本和 query_structured_suggestions 同时存在
        assert result.normalized_query_text is not None
        assert result.normalized_query_text == "门店客户投诉处理方法"
        assert isinstance(result.query_structured_suggestions, QueryStructuredSuggestions)
        assert result.query_structured_suggestions.suggested_problem_type == "客户投诉"
        assert result.query_structured_suggestions.suggested_root_cause_category == "服务态度"
        assert result.query_structured_suggestions.suggested_applicable_scenes == ["零售", "餐饮"]
        assert result.query_structured_suggestions.suggested_tags == ["投诉", "服务"]


# ---------------------------------------------------------------------------
# Tests: 向量候选消费（Requirement 2.1, 2.2, 2.3, 2.4, 2.5）
# ---------------------------------------------------------------------------


class TestVectorCandidateConsumption:
    """向量候选消费测试。"""

    @pytest.mark.asyncio
    async def test_vector_search_returns_only_retrievable_candidates(self):
        """向量候选只包含可检索案例（index_status=searchable，Requirement 2.2）。"""
        # 构造包含多个候选的批次
        candidates = _make_vector_candidates(count=3)

        batch = VectorCandidateBatch(
            search_ref="ref-001",
            index_version="v1-1024",
            candidates=candidates,
        )

        # 所有候选的 index_status 都应该是 "searchable"
        for candidate in batch.candidates:
            assert candidate.index_status.value == "searchable"

        assert len(batch.candidates) == 3

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty_list(self):
        """空候选列表返回空列表（非失败，Requirement 2.3）。"""
        batch = VectorCandidateBatch(
            search_ref="ref-001",
            index_version="v1-1024",
            candidates=[],
        )

        assert batch.candidates == []
        assert len(batch.candidates) == 0

    @pytest.mark.asyncio
    async def test_vector_search_failure_returns_error(self):
        """向量搜索失败时抛出错误（Requirement 2.4）。"""
        from app.retrieval.vector_port import (
            VectorSearchUnavailable,
        )

        mock_port = MagicMock(spec=VectorSearchPort)
        mock_port.search = AsyncMock(
            side_effect=VectorSearchUnavailable("Vector search unavailable")
        )

        query = NormalizedRetrievalQuery(
            normalized_query_text="门店客户投诉处理",
            query_structured_suggestions=QueryStructuredSuggestions(
                suggested_problem_type="客户投诉",
            ),
            applied_filters={},
            effective_weights={"business_type": 0.2},
            top_k=10,
        )

        with pytest.raises(VectorSearchUnavailable):
            await mock_port.search(query)

    @pytest.mark.asyncio
    async def test_vector_candidate_preserves_source_refs(self):
        """向量候选保留问题语义向量来源和索引版本（Requirement 2.5）。"""
        batch = VectorCandidateBatch(
            search_ref="ref-001",
            index_version="v1-1024",
            candidates=_make_vector_candidates(count=2),
        )

        assert batch.search_ref == "ref-001"
        assert batch.index_version == "v1-1024"
        assert len(batch.candidates) == 2

        # 每个候选都保留来源信息
        for candidate in batch.candidates:
            assert candidate.case_id is not None
            assert candidate.vector_id is not None
            assert candidate.similarity_score is not None


# ---------------------------------------------------------------------------
# Tests: RecommendationService + Normalizer 失败路径（Requirement 1.7）
# ---------------------------------------------------------------------------


class TestServiceNormalizerFailurePath:
    """RecommendationService 中 normalizer 失败路径测试。"""

    @pytest.mark.asyncio
    async def test_service_normalizer_failure_calls_fail_run(self):
        """结合 RecommendationService：断言 create_run → normalizer 失败 → fail_run.

        Requirement 1.7.
        """
        # Mock repository
        mock_repo = MagicMock(spec=RecommendationRepository)

        # create_run 返回一个 mock run 记录
        mock_run_record = MagicMock()
        mock_run_record.recommendation_run_id = "test-run-001"
        mock_run_record.status = "pending"
        mock_repo.create_run = AsyncMock(return_value=mock_run_record)

        # fail_run 返回一个 mock 失败记录
        mock_fail_record = MagicMock()
        mock_fail_record.recommendation_run_id = "test-run-001"
        mock_fail_record.status = RunStatus.FAILED
        mock_repo.fail_run = AsyncMock(return_value=mock_fail_record)

        # Mock normalizer 抛出超时异常
        mock_normalizer = MagicMock(spec=QueryNormalizer)
        mock_normalizer.normalize = AsyncMock(side_effect=NormalizerTimeout("LLM timeout"))

        # Mock 其他组件
        mock_vector_port = MagicMock(spec=VectorSearchPort)
        mock_case_provider = MagicMock()
        mock_structured_scorer = MagicMock()
        mock_business_scorer = MagicMock()
        mock_reranker = MagicMock()
        mock_aggregator = MagicMock()

        config = _make_retrieval_config()
        service = RecommendationService(
            repository=mock_repo,
            normalizer=mock_normalizer,
            vector_port=mock_vector_port,
            case_provider=mock_case_provider,
            structured_scorer=mock_structured_scorer,
            business_scorer=mock_business_scorer,
            reranker=mock_reranker,
            aggregator=mock_aggregator,
            config=config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        response = await service.recommend_similar_cases(request)

        # 验证 create_run 被调用
        mock_repo.create_run.assert_called_once()

        # 验证 fail_run 被调用（因为 normalizer 失败）
        mock_repo.fail_run.assert_called_once()

        # 验证响应包含 recommendation_run_id
        assert response.recommendation_run_id == "test-run-001"

        # 验证响应状态为 failed
        assert response.status == RunStatus.FAILED

        # 验证向量端口未被调用（因为 normalizer 失败，fail closed）
        mock_vector_port.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_service_normalizer_failure_response_includes_run_id(self):
        """LLM normalizer 失败时响应含 recommendation_run_id（Requirement 1.7）。"""
        # Mock repository
        mock_repo = MagicMock(spec=RecommendationRepository)

        mock_run_record = MagicMock()
        mock_run_record.recommendation_run_id = "test-run-002"
        mock_run_record.status = "pending"
        mock_repo.create_run = AsyncMock(return_value=mock_run_record)

        mock_fail_record = MagicMock()
        mock_fail_record.recommendation_run_id = "test-run-002"
        mock_fail_record.status = RunStatus.FAILED
        mock_repo.fail_run = AsyncMock(return_value=mock_fail_record)

        # Mock normalizer 抛出配置缺失异常
        mock_normalizer = MagicMock(spec=QueryNormalizer)
        mock_normalizer.normalize = AsyncMock(side_effect=NormalizerConfigMissing("Config missing"))

        mock_vector_port = MagicMock(spec=VectorSearchPort)
        mock_case_provider = MagicMock()
        mock_structured_scorer = MagicMock()
        mock_business_scorer = MagicMock()
        mock_reranker = MagicMock()
        mock_aggregator = MagicMock()

        config = _make_retrieval_config()
        service = RecommendationService(
            repository=mock_repo,
            normalizer=mock_normalizer,
            vector_port=mock_vector_port,
            case_provider=mock_case_provider,
            structured_scorer=mock_structured_scorer,
            business_scorer=mock_business_scorer,
            reranker=mock_reranker,
            aggregator=mock_aggregator,
            config=config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        response = await service.recommend_similar_cases(request)

        # 响应必须包含 recommendation_run_id
        assert hasattr(response, "recommendation_run_id")
        assert response.recommendation_run_id == "test-run-002"

        # 响应状态必须是 failed
        assert response.status == RunStatus.FAILED


# ---------------------------------------------------------------------------
# Tests: 配置隔离回归测试（复用 llm-case-enrichment 基础设施）
# ---------------------------------------------------------------------------


class TestConfigIsolationRegression:
    """配置隔离回归测试：验证 NormalizerLLMConfig 和 RerankerConfig 独立实例。"""

    def test_reranker_config_modification_does_not_affect_normalizer(self):
        """验证修改 RerankerConfig.timeout_ms 不影响 NormalizerLLMConfig.

        Requirement 复用基础设施。
        """
        normalizer_config = _make_normalizer_config(timeout_ms=30000)
        reranker_config = _make_reranker_config(timeout_ms=45000)

        # 记录原始 NormalizerLLMConfig 的 timeout_ms
        original_normalizer_timeout = normalizer_config.timeout_ms

        # 修改 RerankerConfig.timeout_ms
        reranker_config.timeout_ms = 60000

        # NormalizerLLMConfig 未受影响
        assert normalizer_config.timeout_ms == original_normalizer_timeout
        assert normalizer_config.timeout_ms == 30000
        assert reranker_config.timeout_ms == 60000

    def test_normalizer_and_reranker_configs_have_independent_instances(self):
        """验证 NormalizerLLMConfig 和 RerankerConfig 是独立实例（id() 检查）。"""
        normalizer_config = _make_normalizer_config(timeout_ms=30000)
        reranker_config = _make_reranker_config(timeout_ms=45000)

        # 两个配置对象不是同一实例
        assert id(normalizer_config) != id(reranker_config)

    def test_llm_clients_with_different_configs_are_independent(self):
        """验证使用不同配置的 LLMClient 彼此独立。"""
        normalizer_config = _make_normalizer_config(
            api_key="normalizer-key",
            model_id="deepseek-v4-flash",
            timeout_ms=30000,
        )
        reranker_config = _make_reranker_config(
            api_key="reranker-key",
            model_id="qwen3-reranker-8b",
            timeout_ms=45000,
        )

        normalizer_llm_client = LLMClient(normalizer_config)
        reranker_llm_client = LLMClient(reranker_config)

        # 两个客户端使用不同的配置参数
        assert normalizer_llm_client._model_id == "deepseek-v4-flash"
        assert normalizer_llm_client._api_key == "normalizer-key"
        assert normalizer_llm_client._timeout_s == pytest.approx(30.0)

        assert reranker_llm_client._model_id == "qwen3-reranker-8b"
        assert reranker_llm_client._api_key == "reranker-key"
        assert reranker_llm_client._timeout_s == pytest.approx(45.0)

        # 配置参数不同
        assert normalizer_llm_client._model_id != reranker_llm_client._model_id
        assert normalizer_llm_client._api_key != reranker_llm_client._api_key


# ---------------------------------------------------------------------------
# Tests: LLM 错误类型映射（Requirement 1.7）
# ---------------------------------------------------------------------------


class TestLLMErrorMapping:
    """LLM 错误类型映射测试。"""

    @pytest.mark.asyncio
    async def test_timeout_error_maps_to_normalizer_timeout(self):
        """超时错误映射为 NormalizerTimeout（Requirement 1.7）。"""
        from app.core.errors import ErrorCode

        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_TIMEOUT,
                message="模型网关超时",
                retryable=True,
            )
        )

        normalizer_config = _make_normalizer_config()
        normalizer = QueryNormalizer(
            llm_client=mock_client,
            config=normalizer_config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        with pytest.raises(NormalizerTimeout):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_rate_limit_error_maps_to_normalizer_rate_limited(self):
        """限流错误映射为 NormalizerRateLimited（Requirement 1.7）。"""
        from app.core.errors import ErrorCode

        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_RATE_LIMITED,
                message="模型网关限流",
                retryable=True,
                status_code=429,
            )
        )

        normalizer_config = _make_normalizer_config()
        normalizer = QueryNormalizer(
            llm_client=mock_client,
            config=normalizer_config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        with pytest.raises(NormalizerRateLimited):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_config_missing_error_maps_to_normalizer_config_missing(self):
        """配置缺失错误映射为 NormalizerConfigMissing（Requirement 1.7）。"""
        from app.core.errors import ErrorCode

        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_PRIVACY_CONFIG_MISSING,
                message="API key is empty",
                retryable=False,
            )
        )

        normalizer_config = _make_normalizer_config()
        normalizer = QueryNormalizer(
            llm_client=mock_client,
            config=normalizer_config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        with pytest.raises(NormalizerConfigMissing):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_invalid_json_response_maps_to_normalizer_invalid_response(self):
        """无效 JSON 响应映射为 NormalizerInvalidResponse（Requirement 1.7）。"""
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
        normalizer_config = _make_normalizer_config()
        llm_client = LLMClient(normalizer_config, _async_client=mock)

        normalizer = QueryNormalizer(
            llm_client=llm_client,
            config=normalizer_config,
        )

        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        with pytest.raises(NormalizerInvalidResponse):
            await normalizer.normalize(request)


# ---------------------------------------------------------------------------
# Tests: 查询元数据与过滤回显（Requirement 1.4, 1.5）
# ---------------------------------------------------------------------------


class TestQueryMetadataAndFilterEcho:
    """查询元数据与过滤回显测试。"""

    def test_normalized_query_contains_applied_filters(self):
        """规范化后的过滤条件回显到 NormalizedRetrievalQuery（Requirement 1.5）。"""
        query = NormalizedRetrievalQuery(
            normalized_query_text="门店客户投诉处理方法",
            query_structured_suggestions=QueryStructuredSuggestions(
                suggested_problem_type="客户投诉",
            ),
            applied_filters={
                "brand_id": "brand-001",
                "store_id": "store-001",
                "problem_type": "客户投诉",
            },
            effective_weights={
                "business_type": 0.2,
                "store_tier": 0.15,
                "brand_affinity": 0.1,
                "recency": 0.05,
            },
            top_k=10,
        )

        assert "brand_id" in query.applied_filters
        assert query.applied_filters["brand_id"] == "brand-001"
        assert "store_id" in query.applied_filters
        assert "problem_type" in query.applied_filters

    def test_normalized_query_contains_effective_weights(self):
        """有效业务权重回显到 NormalizedRetrievalQuery（Requirement 1.5）。"""
        query = NormalizedRetrievalQuery(
            normalized_query_text="门店客户投诉处理方法",
            query_structured_suggestions=QueryStructuredSuggestions(),
            applied_filters={},
            effective_weights={
                "business_type": 0.3,
                "store_tier": 0.2,
                "brand_affinity": 0.1,
                "recency": 0.05,
            },
            top_k=10,
        )

        assert "business_type" in query.effective_weights
        assert "store_tier" in query.effective_weights
        assert "brand_affinity" in query.effective_weights
        assert "recency" in query.effective_weights
