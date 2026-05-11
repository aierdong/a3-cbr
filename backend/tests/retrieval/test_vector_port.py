"""VectorSearchPort 单元测试。

测试 VectorSearchPort 的：
1. Feature Flag gate
2. 成功路径：正常调用向量搜索、返回可检索候选
3. 失败路径：timeout、unavailable、invalid_response
4. 批次级必选字段校验：search_ref、index_version
5. 候选级必选字段校验：case_id、vector_id、similarity_score、index_status
6. index_status 过滤：只保留 searchable 候选
7. 空候选返回空列表（非失败）
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import ErrorCode
from app.retrieval.schemas import (
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
)
from app.retrieval.vector_port import (
    VectorCandidateBatch,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_normalized_query(
    normalized_text: str = "门店客户投诉处理方法",
    top_k: int = 10,
    applied_filters: dict | None = None,
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
        applied_filters=applied_filters or {},
        effective_weights={
            "business_type": 0.2,
            "store_tier": 0.15,
            "brand_affinity": 0.1,
            "recency": 0.05,
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


# ---------------------------------------------------------------------------
# Tests: 成功路径
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning:pydantic.main")
class TestVectorSearchSuccess:
    """向量搜索成功场景。"""

    @pytest.mark.asyncio
    async def test_search_returns_valid_batch(self):
        """成功调用向量搜索并返回 VectorCandidateBatch。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response()
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        result = await port.search(query)

        assert isinstance(result, VectorCandidateBatch)
        assert result.search_ref == "ref-001"
        assert result.index_version == "v1-1024"
        assert len(result.candidates) == 1

    @pytest.mark.asyncio
    async def test_invalid_index_status_raises_invalid_response(self):
        """无效 index_status 字符串（如 'unsearchable'）抛出 VectorSearchInvalidResponse。

        VectorSearchIndexStatus 仅定义 SEARCHABLE="searchable"，其他字符串值在
        _validate_candidate 的枚举转换阶段失败，视为 invalid_response。
        """
        # 使用 model_construct 绕过 Pydantic 构造校验，模拟上游返回非法枚举字符串
        raw_candidate = {
            "case_id": "case-002",
            "vector_id": "vec-002",
            "similarity_score": 0.88,
            "distance": 0.12,
            "case_updated_at": datetime(2025, 1, 2),
            "input_content_hash": "hash002",
            "index_status": "unsearchable",  # 非法的 index_status 字符串
            "filter_metadata": _make_default_filter_metadata(),
        }
        invalid_candidate = VectorSearchCandidate.model_construct(**raw_candidate)

        # 使用 model_construct 构造响应以避免触发 Pydantic 序列化警告
        raw_response = {
            "items": [invalid_candidate],
            "query_metadata": VectorSearchQueryMetadata(
                query_hash="hash-query",
                model_id="bge-large",
                dimension=1024,
                filters_applied={},
                total_candidates_considered=1,
                search_ref="ref-001",
                index_version="v1-1024",
            ),
        }
        response = VectorSearchResponse.model_construct(**raw_response)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_empty_candidates_returns_empty_list(self):
        """空候选列表返回空列表（非失败）。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response(candidates=[])
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        result = await port.search(query)

        assert isinstance(result, VectorCandidateBatch)
        assert result.search_ref == "ref-001"
        assert result.index_version == "v1-1024"
        assert result.candidates == []

    @pytest.mark.asyncio
    async def test_search_preserves_candidate_fields(self):
        """候选字段完整保留：case_id、vector_id、similarity_score、distance、index_status。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response()
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        result = await port.search(query)

        candidate = result.candidates[0]
        assert candidate.case_id == "case-001"
        assert candidate.vector_id == "vec-001"
        assert candidate.similarity_score == 0.95
        assert candidate.distance == 0.05
        assert candidate.index_status == VectorSearchIndexStatus.SEARCHABLE


# ---------------------------------------------------------------------------
# Tests: 批次级必选字段校验
# ---------------------------------------------------------------------------


class TestBatchLevelValidation:
    """批次级必选字段校验：search_ref、index_version。"""

    @pytest.mark.asyncio
    async def test_missing_search_ref_raises_invalid_response(self):
        """缺少 search_ref 时抛出 VectorSearchInvalidResponse。"""
        # 使用 model_construct 绕过 min_length 校验，模拟上游返回空字符串
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
        response = VectorSearchResponse(items=[valid_candidate], query_metadata=meta)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

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
        response = VectorSearchResponse(items=[valid_candidate], query_metadata=meta)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_version" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_both_envelope_fields_raises_invalid_response(self):
        """search_ref 和 index_version 都缺失时抛出 VectorSearchInvalidResponse。"""
        meta = VectorSearchQueryMetadata.model_construct(
            query_hash="hash-query",
            model_id="bge-large",
            dimension=1024,
            filters_applied={},
            total_candidates_considered=1,
            search_ref="",
            index_version="",
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
        response = VectorSearchResponse(items=[valid_candidate], query_metadata=meta)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse):
            await port.search(query)


# ---------------------------------------------------------------------------
# Tests: 候选级必选字段校验
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning:pydantic.main")
class TestCandidateLevelValidation:
    """候选级必选字段校验：case_id、vector_id、similarity_score、index_status。"""

    @pytest.mark.asyncio
    async def test_missing_case_id_raises_invalid_response(self):
        """缺少 case_id 时抛出 VectorSearchInvalidResponse。"""
        # 构造一个上游响应，其中候选的 case_id 为 None
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
        # 使用 VectorSearchCandidate.model_construct 绕过 case_id 必填校验
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)
        response = _make_vector_search_response(candidates=[candidate])

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

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
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

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
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

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
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_index_status_raises_invalid_response(self):
        """index_status 为无效枚举值时抛出 VectorSearchInvalidResponse。"""
        raw_candidate = {
            "case_id": "case-001",
            "vector_id": "vec-001",
            "similarity_score": 0.95,
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": "not_a_valid_status",  # 无效枚举值
            "filter_metadata": _make_default_filter_metadata(),
        }
        # 使用 model_construct 绕过 index_status 枚举校验
        candidate = VectorSearchCandidate.model_construct(**raw_candidate)

        # 使用 model_construct 构造响应以避免触发 Pydantic 序列化警告
        raw_response = {
            "items": [candidate],
            "query_metadata": VectorSearchQueryMetadata(
                query_hash="hash-query",
                model_id="bge-large",
                dimension=1024,
                filters_applied={},
                total_candidates_considered=1,
                search_ref="ref-001",
                index_version="v1-1024",
            ),
        }
        response = VectorSearchResponse.model_construct(**raw_response)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_status" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: 错误语义映射
# ---------------------------------------------------------------------------


class TestErrorSemanticMapping:
    """错误语义映射：timeout、unavailable、invalid_response。"""

    @pytest.mark.asyncio
    async def test_timeout_error_raises_vector_search_timeout(self):
        """上游超时映射为 VectorSearchTimeout。"""
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
    async def test_unavailable_error_raises_vector_search_unavailable(self):
        """上游不可用映射为 VectorSearchUnavailable。"""
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
    async def test_rate_limit_error_raises_vector_search_unavailable(self):
        """上游限流映射为 VectorSearchUnavailable。"""
        import httpx
        import openai

        req = httpx.Request("POST", "https://api.example.com/vector/search")
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            side_effect=openai.RateLimitError(
                "Rate limit exceeded",
                response=httpx.Response(429, request=req),
                body=None,
            )
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchUnavailable) as exc_info:
            await port.search(query)

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_VECTOR_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_generic_error_raises_vector_search_unavailable(self):
        """其他错误（供应商失败）映射为 VectorSearchUnavailable。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            side_effect=RuntimeError("Vector search provider error")
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchUnavailable) as exc_info:
            await port.search(query)

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_VECTOR_UNAVAILABLE


# ---------------------------------------------------------------------------
# Tests: 候选过滤与可检索性
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning:pydantic.main")
class TestCandidateRetrievability:
    """候选可检索性过滤：index_status 为 searchable 才保留。"""

    @pytest.mark.asyncio
    async def test_invalid_index_status_strings_raise_invalid_response(self):
        """无效 index_status 字符串（'failed'、'archived'）抛出 VectorSearchInvalidResponse。

        VectorSearchIndexStatus 仅定义 SEARCHABLE="searchable"，其他字符串值在
        _validate_candidate 的枚举转换阶段失败，视为 invalid_response。
        """
        # 使用 model_construct 绕过 Pydantic 构造校验，模拟上游返回非法枚举字符串
        raw_data_1 = {
            "case_id": "case-001",
            "vector_id": "vec-001",
            "similarity_score": 0.95,
            "distance": 0.05,
            "case_updated_at": datetime(2025, 1, 1),
            "input_content_hash": "hash001",
            "index_status": "failed",  # 非法 index_status 字符串
            "filter_metadata": _make_default_filter_metadata(),
        }
        raw_data_2 = {
            "case_id": "case-002",
            "vector_id": "vec-002",
            "similarity_score": 0.88,
            "distance": 0.12,
            "case_updated_at": datetime(2025, 1, 2),
            "input_content_hash": "hash002",
            "index_status": "archived",  # 非法 index_status 字符串
            "filter_metadata": _make_default_filter_metadata(),
        }
        candidates = [
            VectorSearchCandidate.model_construct(**raw_data_1),
            VectorSearchCandidate.model_construct(**raw_data_2),
        ]

        # 使用 model_construct 构造响应以避免触发 Pydantic 序列化警告
        raw_response = {
            "items": candidates,
            "query_metadata": VectorSearchQueryMetadata(
                query_hash="hash-query",
                model_id="bge-large",
                dimension=1024,
                filters_applied={},
                total_candidates_considered=2,
                search_ref="ref-001",
                index_version="v1-1024",
            ),
        }
        response = VectorSearchResponse.model_construct(**raw_response)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid_index_status(self):
        """有效 + 无效 index_status 混合时，仅有效候选通过校验。

        VectorSearchIndexStatus.SEARCHABLE 的候选通过；
        非法字符串（如 'degraded'）抛出 VectorSearchInvalidResponse。
        """
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
        raw_data = {
            "case_id": "case-002",
            "vector_id": "vec-002",
            "similarity_score": 0.88,
            "distance": 0.12,
            "case_updated_at": datetime(2025, 1, 2),
            "input_content_hash": "hash002",
            "index_status": "degraded",  # 非法 index_status 字符串
            "filter_metadata": _make_default_filter_metadata(),
        }
        invalid_candidate = VectorSearchCandidate.model_construct(**raw_data)

        # 使用 model_construct 构造响应以避免触发 Pydantic 序列化警告
        raw_response = {
            "items": [valid_candidate, invalid_candidate],
            "query_metadata": VectorSearchQueryMetadata(
                query_hash="hash-query",
                model_id="bge-large",
                dimension=1024,
                filters_applied={},
                total_candidates_considered=2,
                search_ref="ref-001",
                index_version="v1-1024",
            ),
        }
        response = VectorSearchResponse.model_construct(**raw_response)

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=response)

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        with pytest.raises(VectorSearchInvalidResponse) as exc_info:
            await port.search(query)

        assert "index_status" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: 向量搜索失败可区分性
# ---------------------------------------------------------------------------


class TestFailureDistinguishability:
    """空候选、可检索候选、向量搜索失败三者可稳定区分。"""

    @pytest.mark.asyncio
    async def test_empty_candidates_vs_failure(self):
        """空候选列表是稳定返回（VectorCandidateBatch），不是异常。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response(candidates=[])
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        # 空候选返回 VectorCandidateBatch，不抛异常
        result = await port.search(query)
        assert isinstance(result, VectorCandidateBatch)
        assert result.candidates == []

    @pytest.mark.asyncio
    async def test_searchable_candidates_vs_failure(self):
        """有可检索候选是成功路径，不抛异常。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            return_value=_make_vector_search_response()
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        result = await port.search(query)
        assert isinstance(result, VectorCandidateBatch)
        assert len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_vector_search_failure_vs_empty(self):
        """向量搜索失败抛异常，与空候选明确区分。"""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(
            side_effect=RuntimeError("Vector search provider unavailable")
        )

        port = VectorSearchPort(search_service=mock_service)
        query = _make_normalized_query()

        # 失败路径抛异常，不返回 VectorCandidateBatch
        with pytest.raises(VectorSearchUnavailable):
            await port.search(query)
