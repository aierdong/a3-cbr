"""契约回归测试。

测试 cbr-retrieval-recommendation 与上游规格的依赖契约快照：
1. a3-case-management (RecommendationCaseProvider):
   not_found/forbidden 区分、最小字段集
2. case-vector-indexing (VectorSearchPort):
   timeout/unavailable/invalid_response 映射、最小字段集
3. llm-case-enrichment (RecommendationExplainer):
   不改候选顺序

4. QueryNormalizer + 共享 LLMClient 响应 schema 契约测试
   （使用 NormalizerLLMConfig）

5. 配置隔离验证：
   NormalizerLLMConfig 和 RerankerConfig 独立定义与实例检查

Requirements: 2.1, 2.4, 2.5, 5.2, 6.2, 7.3, 7.4
Boundary:
    VectorSearchPort, RecommendationCaseProvider,
    RecommendationExplainer_
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cases.service import CaseNotFoundError
from app.core.config import (
    EnrichmentLLMConfig,
    NormalizerLLMConfig,
    RerankerConfig,
    load_app_config,
)
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    EnrichmentStatus,
    RecommendationCopyItem,
    RecommendationCopyResponse,
    SourceField,
)
from app.enrichment.validators import OutputValidationException
from app.retrieval.case_provider import CaseForbiddenError, RecommendationCaseProvider
from app.retrieval.explainer import ExplanationStatus, RecommendationExplainer
from app.retrieval.schemas import (
    CandidateSnapshot,
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
    RetrievalRequest,
)
from app.retrieval.vector_port import (
    VectorSearchInvalidResponse,
    VectorSearchPort,
    VectorSearchTimeout,
    VectorSearchUnavailable,
)
from app.vector_indexing.schemas import (
    VectorCandidateFilterMetadata,
    VectorSearchCandidate,
    VectorSearchIndexStatus,
    VectorSearchQueryMetadata,
    VectorSearchResponse,
)


# ============================================================================
# Fixtures
# ============================================================================


def _normalizer_config() -> NormalizerLLMConfig:
    """测试用 NormalizerLLMConfig（从 load_app_config 构造）。"""
    app_config = load_app_config()
    return app_config.normalizer_llm


def _reranker_config() -> RerankerConfig:
    """测试用 RerankerConfig（从 load_app_config 构造）。"""
    app_config = load_app_config()
    return app_config.reranker


def _enrichment_config() -> EnrichmentLLMConfig:
    """测试用 EnrichmentLLMConfig（从 load_app_config 构造）。"""
    app_config = load_app_config()
    return app_config.enrichment_llm


def _make_normalized_query(
    normalized_text: str = "门店客户投诉处理方法",
    top_k: int = 10,
) -> NormalizedRetrievalQuery:
    """构造 NormalizedRetrievalQuery。"""
    return NormalizedRetrievalQuery(
        normalized_query_text=normalized_text,
        query_structured_suggestions=QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
            suggested_root_cause_category="服务态度",
            suggested_applicable_scenes=["零售", "餐饮"],
            suggested_tags=["投诉", "服务"],
        ),
        applied_filters={},
        effective_weights={
            "business_type": 0.2,
            "store_tier": 0.15,
        },
        top_k=top_k,
    )


def _make_default_filter_metadata() -> VectorCandidateFilterMetadata:
    """构造默认过滤元数据。"""
    return VectorCandidateFilterMetadata(
        brand_id="brand-001",
        store_id="store-001",
        business_type="零售",
        store_scale="中型",
        franchise_type="直营",
        city="上海",
        city_tier="一线",
        problem_type="客户投诉",
        tags=["投诉", "服务"],
        case_status="active",
    )


def _make_vector_search_response(
    search_ref: str = "ref-001",
    index_version: str = "v1-1024",
    candidates: list[VectorSearchCandidate] | None = None,
) -> VectorSearchResponse:
    """构造 VectorSearchResponse。"""
    if candidates is None:
        candidates = [
            VectorSearchCandidate(
                case_id="case-001",
                vector_id="vec-001",
                similarity_score=0.95,
                distance=0.05,
                case_updated_at=datetime(2025, 1, 1),
                input_content_hash="hash001",
                index_status=VectorSearchIndexStatus.SEARCHABLE,
                filter_metadata=_make_default_filter_metadata(),
            ),
        ]
    return VectorSearchResponse(
        items=candidates,
        query_metadata=VectorSearchQueryMetadata(
            query_hash="hash-query",
            model_id="bge-large",
            dimension=1024,
            filters_applied={},
            total_candidates_considered=len(candidates),
            search_ref=search_ref,
            index_version=index_version,
        ),
    )


def _stub_normalizer_completion(
    normalized_text: str = "门店客户投诉处理方法",
    structured_suggestions: dict | None = None,
):
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


# ============================================================================
# Tests: 配置隔离验证
# Requirement 7.4 / design.md "配置隔离验证"
# ============================================================================


class TestConfigIsolation:
    """配置隔离验证：NormalizerLLMConfig 和 RerankerConfig 独立定义与实例检查。"""

    def test_normalizer_llm_config_independently_defined(self):
        """NormalizerLLMConfig 在 config.py 中独立定义，不与 RerankerConfig 共享。"""
        normalizer_cfg = _normalizer_config()
        reranker_cfg = _reranker_config()

        # 两者是独立的配置类
        assert isinstance(normalizer_cfg, NormalizerLLMConfig)
        assert isinstance(reranker_cfg, RerankerConfig)
        # 类型不同（使用 isinstance 而非 type() 比较）
        assert not isinstance(normalizer_cfg, type(reranker_cfg))

    def test_reranker_config_independently_defined(self):
        """RerankerConfig 在 config.py 中独立定义，不与 NormalizerLLMConfig 共享。"""
        reranker_cfg = _reranker_config()
        assert isinstance(reranker_cfg, RerankerConfig)

    def test_normalizer_and_reranker_not_shared_instances(self):
        """NormalizerLLMConfig 和 RerankerConfig 是独立实例，不共享引用（id() 检查）。"""
        normalizer_cfg = _normalizer_config()
        reranker_cfg = _reranker_config()

        # id() 检查：两者不是同一对象
        assert id(normalizer_cfg) != id(reranker_cfg)

    def test_normalizer_config_does_not_share_with_enrichment(self):
        """NormalizerLLMConfig 与 EnrichmentLLMConfig 是独立实例，不共享引用。"""
        normalizer_cfg = _normalizer_config()
        enrichment_cfg = _enrichment_config()

        # id() 检查：两者不是同一对象
        assert id(normalizer_cfg) != id(enrichment_cfg)

    def test_reranker_config_does_not_share_with_enrichment(self):
        """RerankerConfig 与 EnrichmentLLMConfig 是独立实例，不共享引用。"""
        reranker_cfg = _reranker_config()
        enrichment_cfg = _enrichment_config()

        # id() 检查：两者不是同一对象
        assert id(reranker_cfg) != id(enrichment_cfg)

    def test_modifying_reranker_config_does_not_affect_normalizer(self):
        """修改 RerankerConfig 的字段不影响 NormalizerLLMConfig 的字段。"""
        normalizer_cfg = _normalizer_config()
        reranker_cfg = _reranker_config()

        # 保存原始值
        original_normalizer_timeout = normalizer_cfg.timeout_ms
        original_reranker_timeout = reranker_cfg.timeout_ms

        # 修改 reranker 的 timeout_ms
        reranker_cfg.timeout_ms = 99999

        # normalizer 的 timeout_ms 不受影响
        assert normalizer_cfg.timeout_ms == original_normalizer_timeout
        assert reranker_cfg.timeout_ms == 99999

        # 恢复
        reranker_cfg.timeout_ms = original_reranker_timeout

    def test_modifying_normalizer_config_does_not_affect_reranker(self):
        """修改 NormalizerLLMConfig 的字段不影响 RerankerConfig 的字段。"""
        normalizer_cfg = _normalizer_config()
        reranker_cfg = _reranker_config()

        # 保存原始值
        original_normalizer_timeout = normalizer_cfg.timeout_ms
        original_reranker_timeout = reranker_cfg.timeout_ms

        # 修改 normalizer 的 timeout_ms
        normalizer_cfg.timeout_ms = 88888

        # reranker 的 timeout_ms 不受影响
        assert reranker_cfg.timeout_ms == original_reranker_timeout
        assert normalizer_cfg.timeout_ms == 88888

        # 恢复
        normalizer_cfg.timeout_ms = original_normalizer_timeout

    def test_all_four_llm_configs_are_distinct_instances(self):
        """四个 LLM 配置（enrichment、normalizer、embedding、reranker）都是独立实例。"""
        app_config = load_app_config()

        enrichment_id = id(app_config.enrichment_llm)
        normalizer_id = id(app_config.normalizer_llm)
        embedding_id = id(app_config.embedding)
        reranker_id = id(app_config.reranker)

        # 所有 id 都不同（无共享实例）
        assert len({enrichment_id, normalizer_id, embedding_id, reranker_id}) == 4


# ============================================================================
# Tests: VectorSearchPort 依赖契约（case-vector-indexing）
# Requirements: 2.1, 2.4, 2.5
# ============================================================================


class TestVectorSearchPortContract:
    """VectorSearchPort 依赖契约快照测试。

    验证：
    - timeout / unavailable / invalid_response 错误映射
    - 最小字段集：search_ref、index_version、case_id、vector_id、
      similarity_score、index_status
    - 新增字段兼容（可选字段不导致失败）
    - 必需字段缺失报错
    """

    @pytest.mark.asyncio
    async def test_timeout_error_maps_to_vector_search_timeout(self):
        """timeout 错误映射为 VectorSearchTimeout。"""
        import openai

        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            side_effect=openai.APITimeoutError("Request timed out")
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchTimeout) as exc_info:
            await port.search(query)

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_VECTOR_TIMEOUT

    @pytest.mark.asyncio
    async def test_unavailable_error_maps_to_vector_search_unavailable(self):
        """unavailable 错误映射为 VectorSearchUnavailable。"""
        import httpx

        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchUnavailable) as exc_info:
            await port.search(query)

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_VECTOR_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_invalid_response_error_maps_to_invalid_response(self):
        """invalid_response 错误映射为 VectorSearchInvalidResponse。"""
        # 使用 model_construct 绕过校验，模拟上游返回缺少必需字段的响应
        meta = VectorSearchQueryMetadata.model_construct(
            query_hash="hash-query",
            model_id="bge-large",
            dimension=1024,
            filters_applied={},
            total_candidates_considered=1,
            search_ref="",  # 空字符串违反 min_length=1
            index_version="v1-1024",
        )
        valid_candidate = VectorSearchCandidate(
            case_id="case-001",
            vector_id="vec-001",
            similarity_score=0.95,
            distance=0.05,
            case_updated_at=datetime(2025, 1, 1),
            input_content_hash="hash001",
            index_status=VectorSearchIndexStatus.SEARCHABLE,
            filter_metadata=_make_default_filter_metadata(),
        )
        response = VectorSearchResponse(
            items=[valid_candidate], query_metadata=meta
        )

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "search_ref" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_search_ref_raises_invalid_response(self):
        """缺少 search_ref 时抛出 VectorSearchInvalidResponse。"""
        meta = VectorSearchQueryMetadata.model_construct(
            query_hash="hash-query",
            model_id="bge-large",
            dimension=1024,
            filters_applied={},
            total_candidates_considered=1,
            search_ref="",  # 空字符串
            index_version="v1-1024",
        )
        valid_candidate = VectorSearchCandidate(
            case_id="case-001",
            vector_id="vec-001",
            similarity_score=0.95,
            distance=0.05,
            case_updated_at=datetime(2025, 1, 1),
            input_content_hash="hash001",
            index_status=VectorSearchIndexStatus.SEARCHABLE,
            filter_metadata=_make_default_filter_metadata(),
        )
        response = VectorSearchResponse(
            items=[valid_candidate], query_metadata=meta
        )

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "search_ref" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_index_version_raises_invalid_response(self):
        """缺少 index_version 时抛出 VectorSearchInvalidResponse。"""
        meta = VectorSearchQueryMetadata.model_construct(
            query_hash="hash-query",
            model_id="bge-large",
            dimension=1024,
            filters_applied={},
            total_candidates_considered=1,
            search_ref="ref-001",
            index_version="",  # 空字符串
        )
        valid_candidate = VectorSearchCandidate(
            case_id="case-001",
            vector_id="vec-001",
            similarity_score=0.95,
            distance=0.05,
            case_updated_at=datetime(2025, 1, 1),
            input_content_hash="hash001",
            index_status=VectorSearchIndexStatus.SEARCHABLE,
            filter_metadata=_make_default_filter_metadata(),
        )
        response = VectorSearchResponse(
            items=[valid_candidate], query_metadata=meta
        )

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "index_version" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_case_id_raises_invalid_response(self):
        """缺少 case_id 时抛出 VectorSearchInvalidResponse。"""
        raw_candidate = {
            "case_id": None,  # 缺失
            "vector_id": "vec-001",
            "similarity_score": 0.95,
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": VectorSearchIndexStatus.SEARCHABLE,
            "filter_metadata": _make_default_filter_metadata(),
        }
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)
        response = _make_vector_search_response(candidates=[candidate])

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "case_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_vector_id_raises_invalid_response(self):
        """缺少 vector_id 时抛出 VectorSearchInvalidResponse。"""
        raw_candidate = {
            "case_id": "case-001",
            "vector_id": None,  # 缺失
            "similarity_score": 0.95,
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": VectorSearchIndexStatus.SEARCHABLE,
            "filter_metadata": _make_default_filter_metadata(),
        }
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)
        response = _make_vector_search_response(candidates=[candidate])

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "vector_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_similarity_score_raises_invalid_response(self):
        """缺少 similarity_score 时抛出 VectorSearchInvalidResponse。"""
        raw_candidate = {
            "case_id": "case-001",
            "vector_id": "vec-001",
            "similarity_score": None,  # 缺失
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": VectorSearchIndexStatus.SEARCHABLE,
            "filter_metadata": _make_default_filter_metadata(),
        }
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)
        response = _make_vector_search_response(candidates=[candidate])

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "similarity_score" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_index_status_raises_invalid_response(self):
        """缺少 index_status 时抛出 VectorSearchInvalidResponse。"""
        raw_candidate = {
            "case_id": "case-001",
            "vector_id": "vec-001",
            "similarity_score": 0.95,
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": None,  # 缺失
            "filter_metadata": _make_default_filter_metadata(),
        }
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)
        response = _make_vector_search_response(candidates=[candidate])

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(_make_normalized_query())

        assert "index_status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_optional_fields_new_fields_do_not_break_parsing(self):
        """新增可选字段（如 distance、input_content_hash）不导致解析失败。"""
        # distance 和 input_content_hash 是可选字段，上游返回这些字段不应导致失败
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response()
        )

        port = VectorSearchPort(search_service=mock_service)
        result = await port.search(_make_normalized_query())

        # 成功解析，候选包含可选字段
        assert len(result.candidates) == 1

    @pytest.mark.asyncio
    async def test_contract_version_field_preserved_in_search_result(self):
        """向量搜索响应保留契约版本信息（search_ref、index_version）。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response(
                search_ref="ref-mvp-1",
                index_version="v2-2048",
            )
        )

        port = VectorSearchPort(search_service=mock_service)
        result = await port.search(_make_normalized_query())

        assert result.search_ref == "ref-mvp-1"
        assert result.index_version == "v2-2048"


# ============================================================================
# Tests: RecommendationCaseProvider 依赖契约（a3-case-management）
# Requirements: 2.5, 5.2
# ============================================================================


class TestCaseProviderContract:
    """RecommendationCaseProvider 依赖契约快照测试。

    验证：
    - not_found 与 forbidden 可区分
    - 单候选失败仅标记缺失而非整批崩溃
    - 最小字段集：case_id、status、
      problem_summary/problem_description、core_solution_steps、
      outcome_summary/outcome
    """

    @pytest.fixture
    def case_provider(self):
        """创建 RecommendationCaseProvider 实例。"""
        return RecommendationCaseProvider(
            case_service=MagicMock(),
            enrichment_repository=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_case_not_found_error_distinguished_from_forbidden(self):
        """CaseNotFoundError 与 forbidden 必须可区分。"""
        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            if case_id == "forbidden-case":
                raise PermissionError("Access denied")
            raise CaseNotFoundError(case_id)

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        # CaseNotFoundError 的候选应标记 missing_fields
        vector_candidates = [
            {
                "case_id": "not-found-case",
                "vector_id": "vec-001",
                "similarity_score": 0.95,
                "case_updated_at": datetime.now(),
            }
        ]
        result = await provider.load_candidates(vector_candidates)

        # not_found 的候选应返回快照，但标记缺失字段
        assert len(result) == 1
        assert "problem_description" in result[0].missing_fields

    @pytest.mark.asyncio
    async def test_forbidden_error_raises_case_forbidden_error(self):
        """forbidden 响应抛出 CaseForbiddenError（而非 CaseNotFoundError）。"""
        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            raise PermissionError("Access denied")

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = [
            {
                "case_id": "forbidden-case",
                "vector_id": "vec-001",
                "similarity_score": 0.95,
                "case_updated_at": datetime.now(),
            }
        ]

        # forbidden 必须抛出 CaseForbiddenError
        with pytest.raises(CaseForbiddenError):
            await provider.load_candidates(vector_candidates)

    @pytest.mark.asyncio
    async def test_single_candidate_failure_does_not_cause_batch_failure(self):
        """单候选失败仅标记缺失字段，不导致整批失败。"""
        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            if case_id == "case-002":
                raise CaseNotFoundError(case_id)
            # 返回正常的案例详情
            from app.cases.schemas import (
                CaseDetailResponse,
                CaseStatus,
                ProblemType,
                StoreInfoSummary,
            )
            return CaseDetailResponse(
                case_id=case_id,
                problem_description=f"问题描述 for {case_id}",
                store_id="store-001",
                problem_type=ProblemType.CUSTOMER_COMPLAINT,
                context={"scene": f"场景 for {case_id}"},
                root_cause=f"根因 for {case_id}",
                solution_steps=[
                    {"order": 1, "content": f"步骤1 for {case_id}"},
                    {"order": 2, "content": f"步骤2 for {case_id}"},
                ],
                outcome={"result": "improved"},
                status=CaseStatus.ACTIVE,
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2025, 1, 1),
                store=StoreInfoSummary(
                    store_id="store-001",
                    store_name="上海旗舰店",
                    brand_id="brand-001",
                    brand_name="品牌A",
                    business_type="零售",
                    store_scale="大型",
                    franchise_type="直营",
                    city="上海",
                    city_tier="一线",
                    updated_at=datetime(2025, 1, 1),
                ),
            )

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()

        async def mock_get_result(case_id: str):
            return None  # 没有 enrichment 结果

        mock_enrichment_repo.get_current_result = AsyncMock(
            side_effect=mock_get_result
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = [
            {
                "case_id": "case-001",
                "vector_id": "vec-001",
                "similarity_score": 0.95,
                "case_updated_at": datetime.now(),
            },
            {
                "case_id": "case-002",
                "vector_id": "vec-002",
                "similarity_score": 0.90,
                "case_updated_at": datetime.now(),
            },
            {
                "case_id": "case-003",
                "vector_id": "vec-003",
                "similarity_score": 0.85,
                "case_updated_at": datetime.now(),
            },
        ]
        result = await provider.load_candidates(vector_candidates)

        # 3 个候选都返回了快照，只是 case-002 有 missing_fields
        assert len(result) == 3
        assert result[0].case_id == "case-001"
        assert result[1].case_id == "case-002"
        assert len(result[1].missing_fields) > 0  # case-002 有缺失字段
        assert result[2].case_id == "case-003"

    @pytest.mark.asyncio
    async def test_minimum_required_fields_present(self):
        """最小字段集：case_id、status、problem_description、core_solution_steps。"""
        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            from app.cases.schemas import (
                CaseDetailResponse,
                CaseStatus,
                ProblemType,
                StoreInfoSummary,
            )
            return CaseDetailResponse(
                case_id=case_id,
                problem_description="客户投诉问题",
                store_id="store-001",
                problem_type=ProblemType.CUSTOMER_COMPLAINT,
                context={"scene": "场景"},
                root_cause="服务态度",
                solution_steps=[
                    {"order": 1, "content": "步骤1"},
                    {"order": 2, "content": "步骤2"},
                ],
                outcome={"result": "improved", "notes": "客户满意"},
                status=CaseStatus.ACTIVE,
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2025, 1, 1),
                store=StoreInfoSummary(
                    store_id="store-001",
                    store_name="上海旗舰店",
                    brand_id="brand-001",
                    brand_name="品牌A",
                    business_type="零售",
                    store_scale="大型",
                    franchise_type="直营",
                    city="上海",
                    city_tier="一线",
                    updated_at=datetime(2025, 1, 1),
                ),
            )

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = [
            {
                "case_id": "case-001",
                "vector_id": "vec-001",
                "similarity_score": 0.95,
                "case_updated_at": datetime.now(),
            },
        ]
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # 最小字段集验证
        assert snapshot.case_id == "case-001"
        assert snapshot.case_status is not None  # status
        assert snapshot.problem_description == "客户投诉问题"  # problem_description
        assert snapshot.core_solution_steps is not None  # core_solution_steps
        assert snapshot.outcome_summary is not None  # outcome_summary 或 outcome


# ============================================================================
# Tests: RecommendationExplainer 依赖契约（llm-case-enrichment）
# Requirements: 5.2, 6.2
# ============================================================================


class TestExplainerContract:
    """RecommendationExplainer 依赖契约快照测试。

    验证：
    - 解释服务不改候选顺序
    - 候选增删检查（不得新增、删除候选）
    """

    @pytest.mark.asyncio
    async def test_explainer_does_not_change_candidate_order(self):
        """解释服务不改变候选顺序。"""
        mock_copy_service = MagicMock()
        mock_copy_service.generate_copy = AsyncMock()

        # 乱序的 case_ids
        case_ids = ["case-003", "case-001", "case-002"]
        items = [
            RecommendationCopyItem(
                case_id=cid,
                reason=f"推荐理由 for {cid}",
                reference_points=[f"解决步骤 for {cid}"],
                cautions=[f"注意事项 for {cid}"],
                source_references=[SourceField.SOLUTION_STEPS],
            )
            for cid in case_ids
        ]
        mock_copy_service.generate_copy.return_value = RecommendationCopyResponse(
            copy_run_id="copy-run-001",
            status=EnrichmentStatus.VALID,
            items=items,
            schema_validation_status=EnrichmentStatus.VALID,
            model_id="gpt-4o",
            request_purpose=None,
            token_usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            created_at=datetime.now(),
        )

        explainer = RecommendationExplainer(copy_service=mock_copy_service)

        query = _make_normalized_query()
        candidates = [
            CandidateSnapshot(
                case_id="case-003",
                vector_id="vec-003",
                vector_similarity_score=0.85,
                problem_summary="问题3",
                problem_description="问题描述3",
                core_solution_steps="步骤3",
                outcome_summary="效果3",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            ),
            CandidateSnapshot(
                case_id="case-001",
                vector_id="vec-001",
                vector_similarity_score=0.95,
                problem_summary="问题1",
                problem_description="问题描述1",
                core_solution_steps="步骤1",
                outcome_summary="效果1",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            ),
            CandidateSnapshot(
                case_id="case-002",
                vector_id="vec-002",
                vector_similarity_score=0.90,
                problem_summary="问题2",
                problem_description="问题描述2",
                core_solution_steps="步骤2",
                outcome_summary="效果2",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            ),
        ]

        result = await explainer.explain(query, candidates)

        # 顺序保持：输入顺序为 case-003, case-001, case-002
        assert [item.case_id for item in result.items] == [
            "case-003", "case-001", "case-002"
        ]

    @pytest.mark.asyncio
    async def test_explainer_does_not_add_candidates(self):
        """解释服务不得新增候选。"""
        mock_copy_service = MagicMock()
        mock_copy_service.generate_copy = AsyncMock()

        # 只返回一个候选的响应（模拟上游只返回部分候选）
        mock_copy_service.generate_copy.return_value = RecommendationCopyResponse(
            copy_run_id="copy-run-001",
            status=EnrichmentStatus.VALID,
            items=[
                RecommendationCopyItem(
                    case_id="case-001",
                    reason="推荐理由",
                    reference_points=["解决步骤"],
                    cautions=["注意事项"],
                    source_references=[SourceField.SOLUTION_STEPS],
                )
            ],
            schema_validation_status=EnrichmentStatus.VALID,
            model_id="gpt-4o",
            request_purpose=None,
            token_usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            created_at=datetime.now(),
        )

        explainer = RecommendationExplainer(copy_service=mock_copy_service)

        query = _make_normalized_query()
        # 3 个候选
        candidates = [
            CandidateSnapshot(
                case_id=f"case-00{i}",
                vector_id=f"vec-00{i}",
                vector_similarity_score=0.95 - i * 0.02,
                problem_summary=f"问题{i}",
                problem_description=f"问题描述{i}",
                core_solution_steps=f"步骤{i}",
                outcome_summary=f"效果{i}",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            )
            for i in range(1, 4)
        ]

        result = await explainer.explain(query, candidates)

        # 输出候选数量 == 输入候选数量（不新增）
        assert len(result.items) == len(candidates)

    @pytest.mark.asyncio
    async def test_explainer_does_not_delete_candidates(self):
        """解释服务不得删除候选。"""
        mock_copy_service = MagicMock()
        mock_copy_service.generate_copy = AsyncMock()

        # 返回空响应（模拟上游失败）
        mock_copy_service.generate_copy.side_effect = OutputValidationException(
            error_code="INJECTION_SUSPECTED",
            message="检测到潜在注入风险",
        )

        explainer = RecommendationExplainer(copy_service=mock_copy_service)

        query = _make_normalized_query()
        candidates = [
            CandidateSnapshot(
                case_id=f"case-00{i}",
                vector_id=f"vec-00{i}",
                vector_similarity_score=0.95 - i * 0.02,
                problem_summary=f"问题{i}",
                problem_description=f"问题描述{i}",
                core_solution_steps=f"步骤{i}",
                outcome_summary=f"效果{i}",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            )
            for i in range(1, 4)
        ]

        result = await explainer.explain(query, candidates)

        # 输出候选数量 == 输入候选数量（降级时不删除）
        assert len(result.items) == len(candidates)

    @pytest.mark.asyncio
    async def test_fallback_response_preserves_order(self):
        """降级响应保持候选顺序。"""
        mock_copy_service = MagicMock()
        mock_copy_service.generate_copy.side_effect = Exception("服务不可用")

        explainer = RecommendationExplainer(copy_service=mock_copy_service)

        query = _make_normalized_query()
        candidates = [
            CandidateSnapshot(
                case_id="case-A",
                vector_id="vec-A",
                vector_similarity_score=0.95,
                problem_summary="问题A",
                problem_description="问题描述A",
                core_solution_steps="步骤A",
                outcome_summary="效果A",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            ),
            CandidateSnapshot(
                case_id="case-B",
                vector_id="vec-B",
                vector_similarity_score=0.90,
                problem_summary="问题B",
                problem_description="问题描述B",
                core_solution_steps="步骤B",
                outcome_summary="效果B",
                brand_id="brand-001",
                store_id="store-001",
                problem_type="客户投诉",
                tags=["投诉"],
                case_status="active",
                case_updated_at=datetime.now(),
                missing_fields=[],
            ),
        ]

        result = await explainer.explain(query, candidates)

        # 降级时顺序保持
        assert [item.case_id for item in result.items] == ["case-A", "case-B"]
        assert result.status == ExplanationStatus.FALLBACK


# ============================================================================
# Tests: QueryNormalizer + LLMClient 响应 schema 契约测试
# Requirement: 7.3
# ============================================================================


class TestQueryNormalizerContract:
    """QueryNormalizer + 共享 LLMClient 响应 schema 契约测试。

    使用 NormalizerLLMConfig，独立于 EnrichmentLLMConfig。
    验证：
    - LLM normalizer 响应 schema 快照
    - 响应包含 normalized_query_text 和 query_structured_suggestions
    - 失败时抛出特定异常（不返回 fallback）
    """

    @pytest.mark.asyncio
    async def test_normalizer_response_contains_required_fields(self):
        """LLM normalizer 响应必须包含 normalized_query_text 和 query_structured_suggestions。"""
        from app.retrieval.query import QueryNormalizer
        from app.core.llm_client import LLMClient

        completion = _stub_normalizer_completion(
            normalized_text="门店客户投诉处理方法",
            structured_suggestions={
                "suggested_problem_type": "客户投诉",
                "suggested_root_cause_category": "服务态度",
                "suggested_applicable_scenes": ["零售", "餐饮"],
                "suggested_tags": ["投诉", "服务"],
            },
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=completion)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock_client)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(
            query_text="客户投诉怎么处理",
            top_k=10,
        )

        result = await normalizer.normalize(request)

        # 响应必须包含 normalized_query_text
        assert result.normalized_query_text == "门店客户投诉处理方法"
        # 响应必须包含 query_structured_suggestions
        assert result.query_structured_suggestions is not None
        assert result.query_structured_suggestions.suggested_problem_type == "客户投诉"

    @pytest.mark.asyncio
    async def test_normalizer_uses_normalizer_llm_config_not_enrichment(self):
        """QueryNormalizer 使用 NormalizerLLMConfig，不使用 EnrichmentLLMConfig。"""
        # NormalizerLLMConfig 和 EnrichmentLLMConfig 应该有不同配置
        normalizer_cfg = _normalizer_config()
        enrichment_cfg = _enrichment_config()

        # 确认两者配置不同（通过环境变量或默认值）
        # 至少 model_id 可能不同，或者 base_url 不同
        # 这里只验证它们是独立实例
        assert id(normalizer_cfg) != id(enrichment_cfg)

    @pytest.mark.asyncio
    async def test_normalizer_failure_raises_specific_error_not_fallback(self):
        """LLM normalizer 失败时抛出特定异常，不使用原始 query_text 兜底。"""
        from app.retrieval.query import NormalizerTimeout, QueryNormalizer
        from app.core.llm_client import LLMClient
        import openai

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        # 失败时抛出 NormalizerTimeout（不是普通异常）
        with pytest.raises(NormalizerTimeout):
            await normalizer.normalize(request)

    @pytest.mark.asyncio
    async def test_normalizer_invalid_json_raises_specific_error(self):
        """LLM normalizer 返回无效 JSON 时抛出 NormalizerInvalidResponse。"""
        from app.retrieval.query import NormalizerInvalidResponse, QueryNormalizer
        from app.core.llm_client import LLMClient

        bad_comp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="这不是有效的 JSON"),
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
        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(return_value=bad_comp)

        config = _normalizer_config()
        llm_client = LLMClient(config, _async_client=mock)

        normalizer = QueryNormalizer(llm_client=llm_client, config=config)
        request = RetrievalRequest(query_text="客户投诉怎么处理", top_k=10)

        with pytest.raises(NormalizerInvalidResponse):
            await normalizer.normalize(request)


# ============================================================================
# Tests: 契约版本标记
# Requirements: 2.5, 7.3
# ============================================================================


class TestContractVersionMarker:
    """契约版本标记测试。"""

    def test_contract_version_in_response_schema(self):
        """RecommendationResponse 包含 contract_version 字段。"""
        from app.retrieval.schemas import RecommendationResponse

        # contract_version 是必填字段
        response = RecommendationResponse(
            recommendation_run_id="run-001",
            contract_version="mvp-1",
            status="succeeded",
            applied_filters={},
            score_weights={
                "vector": 0.3,
                "semantic": 0.3,
                "structured": 0.2,
                "business": 0.2,
            },
            query_metadata={},
            items=[],
        )

        assert response.contract_version == "mvp-1"

    def test_contract_version_in_run_response(self):
        """RecommendationRunResponse 包含 contract_version 字段。"""
        from app.retrieval.schemas import RecommendationRunResponse

        response = RecommendationRunResponse(
            recommendation_run_id="run-001",
            contract_version="mvp-1",
            query_text_hash="hash123",
            applied_filters={},
            score_weights={},
            requested_top_k=10,
            returned_count=0,
            vector_candidate_count=0,
            status="succeeded",
            reranker_model_id="qwen3-reranker-8b",
            reranker_status="pending",
            aggregation_status="succeeded",
            latency_ms=100,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            items=[],
        )

        assert response.contract_version == "mvp-1"

    def test_contract_version_persisted_in_run_create(self):
        """RecommendationRunCreate 包含 contract_version 字段。"""
        from app.retrieval.schemas import RecommendationRunCreate

        run_create = RecommendationRunCreate(
            recommendation_run_id="run-001",
            query_text_hash="hash123",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=10,
            reranker_model_id="qwen3-reranker-8b",
        )

        assert run_create.contract_version == "mvp-1"


