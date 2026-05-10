"""VectorSearchService：查询向量生成、过滤语义校验与隐私日志边界。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.repository_types import (
    VectorCandidateFilterPayload,
    VectorCandidateRecord,
    VectorSearchQuery,
)
from app.vector_indexing.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    VectorCandidateFilterMetadata,
    VectorSearchFilters,
    VectorSearchRequest,
)
from app.vector_indexing.search import VectorSearchService, VectorSearchValidationError


def _query_hash(query_text: str) -> str:
    composer = EmbeddingInputComposer()
    composed = composer.compose_query_input(query_text)
    return hashlib.sha256(composed.text.encode("utf-8")).hexdigest()


def _service(embed_mock: AsyncMock, *, repository: AsyncMock | None = None) -> VectorSearchService:
    repo = AsyncMock(search=AsyncMock(return_value=[])) if repository is None else repository
    return VectorSearchService(
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(embed_for_query=embed_mock),
        repository=repo,
    )


@pytest.mark.asyncio
async def test_search_embed_once_returns_empty_items(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """合法查询应单次嵌入、单次仓储检索；空候选时 items=[] 且 total_candidates_considered=0。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=4,
            vector=[0.1, 0.2, 0.3, 0.4],
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=[]))
    svc = _service(embed_mock, repository=repo)
    req = VectorSearchRequest(query_text="  门店客流下降怎么办  ", top_k=5)

    caplog.set_level(logging.INFO, logger="app.vector_indexing.search")
    resp = await svc.search(req)

    embed_mock.assert_awaited_once()
    emb_req: EmbeddingRequest = embed_mock.await_args.args[0]
    composed_text = EmbeddingInputComposer().compose_query_input(req.query_text).text
    assert emb_req.text == composed_text
    expected_fp = _query_hash(req.query_text)
    assert emb_req.content_fingerprint == expected_fp

    repo.search.assert_awaited_once()
    q_arg: VectorSearchQuery = repo.search.await_args.args[0]
    assert q_arg == VectorSearchQuery(
        query_embedding=[0.1, 0.2, 0.3, 0.4],
        top_k=5,
    )

    assert resp.items == []
    assert resp.query_metadata.query_hash == expected_fp
    assert resp.query_metadata.model_id == "bge-large-zh"
    assert resp.query_metadata.dimension == 4
    assert resp.query_metadata.filters_applied == {}
    assert resp.query_metadata.total_candidates_considered == 0


@pytest.mark.asyncio
async def test_search_with_filters_metadata(caplog: pytest.LogCaptureFixture) -> None:
    """含 filters 时 metadata.filters_applied 应反映非空过滤字段。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="m1",
            embedding_dimension=2,
            vector=[1.0, 0.0],
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=[]))
    svc = _service(embed_mock, repository=repo)
    t0 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    filters = VectorSearchFilters(
        brand_id="b1",
        tags=["a", "b"],
        created_at_from=t0,
        created_at_to=t1,
        case_updated_at_from=t0,
        case_updated_at_to=t1,
    )
    req = VectorSearchRequest(query_text="x", top_k=10, filters=filters)

    caplog.set_level(logging.INFO, logger="app.vector_indexing.search")
    resp = await svc.search(req)

    assert resp.query_metadata.filters_applied == filters.model_dump(mode="json", exclude_none=True)

    q_arg: VectorSearchQuery = repo.search.await_args.args[0]
    assert q_arg.brand_id == "b1"
    assert q_arg.tags == ["a", "b"]
    assert q_arg.case_updated_at_from == t0
    assert q_arg.case_updated_at_to == t1


@pytest.mark.asyncio
async def test_build_query_vector_returns_embedding_and_metadata() -> None:
    """build_query_vector 应返回 EmbeddingResult 与一致的 query_metadata。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="m",
            embedding_dimension=3,
            vector=[0.0, 1.0, 2.0],
        ),
    )
    svc = _service(embed_mock)
    req = VectorSearchRequest(query_text="probe")

    emb, meta = await svc.build_query_vector(req)

    assert emb.embedding_model_id == "m"
    assert meta.query_hash == _query_hash("probe")
    assert meta.model_id == "m"
    assert meta.dimension == 3


def test_pydantic_rejects_top_k_out_of_bounds() -> None:
    """VectorSearchRequest 静态约束：top_k 越界应由 Pydantic 捕获。"""
    with pytest.raises(ValidationError):
        VectorSearchRequest(query_text="ok", top_k=101)


@pytest.mark.asyncio
async def test_whitespace_only_query_rejected_at_service() -> None:
    """仅空白字符的 query_text 应在业务层拒绝（Pydantic 可能放行）。"""
    embed_mock = AsyncMock()
    svc = _service(embed_mock)
    req = VectorSearchRequest(query_text="   ", top_k=10)

    with pytest.raises(VectorSearchValidationError) as ei:
        await svc.search(req)

    assert ei.value.field == "query_text"
    assert ei.value.error_code == ErrorCode.VALIDATION_ERROR
    embed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_tags_empty_string_rejected() -> None:
    """filters.tags 含空字符串时字段级校验失败。"""
    embed_mock = AsyncMock()
    svc = _service(embed_mock)
    req = VectorSearchRequest(
        query_text="q",
        top_k=10,
        filters=VectorSearchFilters(tags=["ok", ""]),
    )

    with pytest.raises(VectorSearchValidationError) as ei:
        await svc.search(req)

    assert ei.value.field == "filters.tags"
    assert ei.value.error_code == ErrorCode.VALIDATION_ERROR
    embed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_case_updated_at_range_invalid() -> None:
    """case_updated_at_from 晚于 case_updated_at_to 时应拒绝。"""
    embed_mock = AsyncMock()
    svc = _service(embed_mock)
    t_hi = datetime(2026, 5, 10, tzinfo=timezone.utc)
    t_lo = datetime(2026, 5, 1, tzinfo=timezone.utc)
    req = VectorSearchRequest(
        query_text="q",
        top_k=10,
        filters=VectorSearchFilters(case_updated_at_from=t_hi, case_updated_at_to=t_lo),
    )

    with pytest.raises(VectorSearchValidationError) as ei:
        await svc.search(req)

    assert ei.value.field == "filters.case_updated_at"
    embed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_created_at_range_invalid() -> None:
    """created_at_from 晚于 created_at_to 时应拒绝。"""
    embed_mock = AsyncMock()
    svc = _service(embed_mock)
    t_hi = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t_lo = datetime(2026, 5, 1, tzinfo=timezone.utc)
    req = VectorSearchRequest(
        query_text="q",
        top_k=10,
        filters=VectorSearchFilters(created_at_from=t_hi, created_at_to=t_lo),
    )

    with pytest.raises(VectorSearchValidationError) as ei:
        await svc.search(req)

    assert ei.value.field == "filters.created_at"
    embed_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_embedding_error_propagates() -> None:
    """embed_for_query 抛出 LLMClientError 时应原样向上传递。"""
    err = LLMClientError(
        error_code=ErrorCode.EMBEDDING_TIMEOUT,
        message="timeout",
        retryable=False,
        status_code=503,
    )
    embed_mock = AsyncMock(side_effect=err)
    svc = _service(embed_mock)

    with pytest.raises(LLMClientError) as ei:
        await svc.search(VectorSearchRequest(query_text="hello", top_k=3))

    assert ei.value is err


@pytest.mark.asyncio
async def test_search_passes_store_problem_type_case_status_to_repository() -> None:
    """结构化过滤：门店、问题类型、案例状态应传入 VectorSearchQuery。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="m",
            embedding_dimension=2,
            vector=[0.0, 1.0],
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=[]))
    svc = _service(embed_mock, repository=repo)
    filters = VectorSearchFilters(
        store_id="s9",
        problem_type="inventory",
        case_status="published",
    )
    req = VectorSearchRequest(query_text="ok", top_k=7, filters=filters)

    await svc.search(req)

    q_arg: VectorSearchQuery = repo.search.await_args.args[0]
    assert q_arg.store_id == "s9"
    assert q_arg.problem_type == "inventory"
    assert q_arg.case_status == "published"
    assert q_arg.top_k == 7


@pytest.mark.asyncio
async def test_search_maps_repository_records_to_items() -> None:
    """仓储返回 VectorCandidateRecord 时应映射为 VectorSearchResponse.items。"""
    cu = datetime(2026, 3, 1, tzinfo=timezone.utc)
    fm = VectorCandidateFilterPayload(
        brand_id="bb",
        store_id="ss",
        problem_type="pt",
        tags=["t1"],
        case_status="open",
    )
    distance_f = 0.15
    records = [
        VectorCandidateRecord(
            case_id="c1",
            vector_id="v1",
            similarity_score=1.0 - distance_f,
            distance=distance_f,
            case_updated_at=cu,
            input_content_hash="abc123",
            filter_metadata=fm,
        ),
    ]
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="emb",
            embedding_dimension=2,
            vector=[1.0, 0.0],
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=records))
    svc = _service(embed_mock, repository=repo)

    resp = await svc.search(VectorSearchRequest(query_text="q", top_k=20))

    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.case_id == "c1"
    assert item.vector_id == "v1"
    assert item.distance == distance_f
    assert item.similarity_score == pytest.approx(1.0 - distance_f)
    assert item.case_updated_at == cu
    assert item.input_content_hash == "abc123"
    assert item.filter_metadata == VectorCandidateFilterMetadata(
        brand_id="bb",
        store_id="ss",
        business_type="",
        store_scale="",
        franchise_type="",
        city="",
        city_tier="",
        problem_type="pt",
        tags=["t1"],
        case_status="open",
    )
    assert resp.query_metadata.total_candidates_considered == 1


@pytest.mark.asyncio
async def test_search_raises_when_repository_missing() -> None:
    """嵌入成功后若未注入仓储应抛出 RuntimeError。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="m",
            embedding_dimension=1,
            vector=[1.0],
        ),
    )
    svc = VectorSearchService(
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(embed_for_query=embed_mock),
        repository=None,
    )

    with pytest.raises(RuntimeError):
        await svc.search(VectorSearchRequest(query_text="hello", top_k=3))


@pytest.mark.asyncio
async def test_logs_do_not_contain_raw_query_text(caplog: pytest.LogCaptureFixture) -> None:
    """日志不得包含完整 query_text。"""
    secret = "这是一段不应出现在日志里的门店机密描述全文"
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="m",
            embedding_dimension=1,
            vector=[1.0],
        ),
    )
    svc = _service(embed_mock)
    caplog.set_level(logging.INFO, logger="app.vector_indexing.search")

    await svc.search(VectorSearchRequest(query_text=secret, top_k=5))

    joined = caplog.text
    assert secret not in joined
