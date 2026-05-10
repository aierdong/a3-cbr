"""VectorRouter API 集成测试（ASGI + dependency_overrides）。

仅 mock VectorIndexService / VectorJobRunner / VectorSearchService，不连接真实 Postgres。

Requirements: 1.3, 2.3, 3.3, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4
Boundary: VectorRouter
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode
from app.main import app
from app.vector_indexing.schemas import (
    CaseVectorRecord,
    DeleteVectorIndexResponse,
    SourceVersion,
    VectorCandidateFilterMetadata,
    VectorErrorStage,
    VectorIndexJobResponse,
    VectorIndexStatus,
    VectorIndexStatusResponse,
    VectorJobStatus,
    VectorJobType,
    VectorSearchCandidate,
    VectorSearchQueryMetadata,
    VectorSearchRequest,
    VectorSearchResponse,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _job_response(
    *,
    job_id: str = "job_001",
    case_id: str = "case_001",
    status: VectorJobStatus = VectorJobStatus.SUCCEEDED,
    error_code: str | None = None,
    error_stage: VectorErrorStage | None = None,
    retry_count: int = 0,
) -> VectorIndexJobResponse:
    now = _utc_now()
    return VectorIndexJobResponse(
        job_id=job_id,
        case_id=case_id,
        job_type=VectorJobType.REFRESH,
        status=status,
        source_version=SourceVersion(case_updated_at=now),
        error_code=error_code,
        error_stage=error_stage,
        retry_count=retry_count,
        started_at=now,
        finished_at=now,
    )


def _vector_record(
    *,
    case_id: str = "case_001",
    degraded_reason: str | None = None,
) -> CaseVectorRecord:
    now = _utc_now()
    return CaseVectorRecord(
        vector_id="vec_001",
        case_id=case_id,
        case_updated_at=now,
        enrichment_id=None,
        enrichment_status=None,
        input_template_version="case_embedding_v1",
        input_content_hash="hash",
        embedding_model_id="bge-large-zh",
        embedding_dimension=1024,
        is_current=True,
        searchable=True,
        degraded_reason=degraded_reason,
        created_at=now,
        updated_at=now,
    )


def _filter_meta() -> VectorCandidateFilterMetadata:
    return VectorCandidateFilterMetadata(
        brand_id="b1",
        store_id="s1",
        business_type="bt",
        store_scale="ss",
        franchise_type="ft",
        city="c",
        city_tier="t1",
        problem_type="pt",
        tags=["x"],
        case_status="open",
    )


def _search_candidate(case_id: str = "case_hit") -> VectorSearchCandidate:
    now = _utc_now()
    return VectorSearchCandidate(
        case_id=case_id,
        vector_id="vec_hit",
        similarity_score=0.9,
        distance=0.1,
        case_updated_at=now,
        input_content_hash="qh",
        filter_metadata=_filter_meta(),
    )


def _search_meta(**kwargs: object) -> VectorSearchQueryMetadata:
    defaults: dict[str, object] = {
        "query_hash": "abc",
        "model_id": "bge-large-zh",
        "dimension": 1024,
        "filters_applied": {"brand_id": "b1"},
        "total_candidates_considered": 1,
    }
    defaults.update(kwargs)
    return VectorSearchQueryMetadata(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def mock_index_service() -> AsyncMock:
    """提供 mock ``VectorIndexService``。"""
    m = AsyncMock()
    m.refresh_case_index.return_value = _job_response()
    m.get_case_status.return_value = VectorIndexStatusResponse(
        case_id="case_001",
        status=VectorIndexStatus.QUEUED,
        latest_job=None,
        current_vector=None,
        message="尚无向量索引任务",
    )
    now = _utc_now()
    m.delete_case_vector.return_value = DeleteVectorIndexResponse(
        success=True,
        deleted_count=1,
        deleted_at=now,
    )
    return m


@pytest.fixture
def mock_job_runner() -> AsyncMock:
    """提供 mock ``VectorJobRunner``。"""
    m = AsyncMock()
    m.retry_job.return_value = _job_response(job_id="job_retry")
    return m


@pytest.fixture
def mock_search_service() -> AsyncMock:
    """提供 mock ``VectorSearchService``。"""
    m = AsyncMock()
    m.search.return_value = VectorSearchResponse(
        items=[_search_candidate()],
        query_metadata=_search_meta(),
    )
    return m


@pytest.fixture
def client(mock_index_service, mock_job_runner, mock_search_service):
    """``httpx.AsyncClient``，通过 ``dependency_overrides`` 注入向量 mock。"""
    from app.vector_indexing.router import (
        get_vector_index_service,
        get_vector_job_runner,
        get_vector_search_service,
    )

    app.dependency_overrides[get_vector_index_service] = (
        lambda: mock_index_service
    )
    app.dependency_overrides[get_vector_job_runner] = (
        lambda: mock_job_runner
    )
    app.dependency_overrides[get_vector_search_service] = (
        lambda: mock_search_service
    )

    yield AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    app.dependency_overrides.clear()


class TestRefreshCaseVectorIndex:
    """POST ``/api/a3-cases/{case_id}/vector-index/refresh``。"""

    @pytest.mark.asyncio
    async def test_refresh_success_returns_succeeded_with_job_id(
        self, client, mock_index_service,
    ):
        """成功刷新返回 HTTP 200、succeeded 状态与 ``job_id``。"""
        mock_index_service.refresh_case_index.return_value = _job_response(
            job_id="job_ok",
            status=VectorJobStatus.SUCCEEDED,
        )
        resp = await client.post(
            "/api/a3-cases/case_001/vector-index/refresh",
            json={"force_rebuild": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job_ok"
        assert data["status"] == "succeeded"
        mock_index_service.refresh_case_index.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_failed_returns_200_with_error_fields(
        self, client, mock_index_service,
    ):
        """刷新失败时契约仍为 200，正文携带 ``failed``、``error_code``、``error_stage``。"""
        mock_index_service.refresh_case_index.return_value = _job_response(
            status=VectorJobStatus.FAILED,
            error_code=ErrorCode.EMBEDDING_TIMEOUT,
            error_stage=VectorErrorStage.EMBEDDING_CALL,
            retry_count=1,
        )
        resp = await client.post(
            "/api/a3-cases/case_001/vector-index/refresh",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_code"] == ErrorCode.EMBEDDING_TIMEOUT
        assert data["error_stage"] == "embedding_call"

    @pytest.mark.asyncio
    async def test_refresh_runtime_returns_500(self, client, mock_index_service):
        """刷新路径未捕获的运行时错误映射为 500 ``INTERNAL_ERROR``。"""
        mock_index_service.refresh_case_index.side_effect = RuntimeError("broken")
        resp = await client.post(
            "/api/a3-cases/case_001/vector-index/refresh",
            json={},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == ErrorCode.INTERNAL_ERROR


class TestCaseVectorIndexStatus:
    """GET ``/api/a3-cases/{case_id}/vector-index``。"""

    @pytest.mark.asyncio
    async def test_status_query_includes_degraded_reason_when_degraded(
        self, client, mock_index_service,
    ):
        """降级状态下 ``current_vector.degraded_reason`` 出现在响应中。"""
        mock_index_service.get_case_status.return_value = VectorIndexStatusResponse(
            case_id="case_001",
            status=VectorIndexStatus.DEGRADED,
            latest_job=None,
            current_vector=_vector_record(degraded_reason="missing_summary"),
        )
        resp = await client.get("/api/a3-cases/case_001/vector-index")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["current_vector"] is not None
        assert body["current_vector"]["degraded_reason"] == "missing_summary"

    @pytest.mark.asyncio
    async def test_status_empty_job_empty_vector(self, client, mock_index_service):
        """无任务且无向量时聚合为 ``queued`` 且两项为空。"""
        mock_index_service.get_case_status.return_value = VectorIndexStatusResponse(
            case_id="case_001",
            status=VectorIndexStatus.QUEUED,
            latest_job=None,
            current_vector=None,
            message="尚无向量索引任务",
        )
        resp = await client.get("/api/a3-cases/case_001/vector-index")
        assert resp.status_code == 200
        d = resp.json()
        assert d["latest_job"] is None
        assert d["current_vector"] is None

    @pytest.mark.asyncio
    async def test_status_published(self, client, mock_index_service):
        """已成功且无降级原因时为 ``published``。"""
        mock_index_service.get_case_status.return_value = VectorIndexStatusResponse(
            case_id="case_001",
            status=VectorIndexStatus.PUBLISHED,
            latest_job=_job_response(status=VectorJobStatus.SUCCEEDED),
            current_vector=_vector_record(degraded_reason=None),
        )
        resp = await client.get("/api/a3-cases/case_001/vector-index")
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"


class TestRetryVectorIndexJob:
    """POST ``/api/vector-index/jobs/{job_id}/retry``。"""

    @pytest.mark.asyncio
    async def test_retry_success_returns_new_job(self, client, mock_job_runner):
        """重试成功返回 HTTP 200 与新 ``job_id``。"""
        mock_job_runner.retry_job.return_value = _job_response(job_id="job_new")
        resp = await client.post("/api/vector-index/jobs/job_old/retry")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "job_new"
        mock_job_runner.retry_job.assert_awaited_once_with("job_old")

    @pytest.mark.asyncio
    async def test_retry_not_allowed_returns_409(self, client, mock_job_runner):
        """不可重试时返回 409 ``VECTOR_RETRY_NOT_ALLOWED``。"""
        from app.vector_indexing.job_runner import VectorJobRetryNotAllowedError

        mock_job_runner.retry_job.side_effect = VectorJobRetryNotAllowedError(
            ErrorCode.VECTOR_RETRY_NOT_ALLOWED,
        )
        resp = await client.post("/api/vector-index/jobs/job_x/retry")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == ErrorCode.VECTOR_RETRY_NOT_ALLOWED

    @pytest.mark.asyncio
    async def test_retry_state_conflict_returns_409(self, client, mock_job_runner):
        """运行中冲突时返回 409 ``VECTOR_STATE_CONFLICT``。"""
        from app.vector_indexing.job_runner import VectorJobRetryNotAllowedError

        mock_job_runner.retry_job.side_effect = VectorJobRetryNotAllowedError(
            ErrorCode.VECTOR_STATE_CONFLICT,
        )
        resp = await client.post("/api/vector-index/jobs/job_run/retry")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == ErrorCode.VECTOR_STATE_CONFLICT

    @pytest.mark.asyncio
    async def test_retry_job_not_found_returns_404(self, client, mock_job_runner):
        """任务不存在返回 404 ``VECTOR_JOB_NOT_FOUND``。"""
        from app.vector_indexing.job_runner import VectorIndexJobNotFoundError

        mock_job_runner.retry_job.side_effect = VectorIndexJobNotFoundError("missing")
        resp = await client.post("/api/vector-index/jobs/missing/retry")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == ErrorCode.VECTOR_JOB_NOT_FOUND


class TestDeleteVectorIndex:
    """POST ``/api/vector-index/delete``。"""

    @pytest.mark.asyncio
    async def test_delete_success(self, client, mock_index_service):
        """成功删除返回 ``deleted_count``。"""
        now = _utc_now()
        mock_index_service.delete_case_vector.return_value = DeleteVectorIndexResponse(
            success=True,
            deleted_count=2,
            deleted_at=now,
        )
        resp = await client.post(
            "/api/vector-index/delete",
            json={
                "case_id": "case_001",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_delete_idempotent_zero(self, client, mock_index_service):
        """幂等：无向量时 ``deleted_count`` 可为 0。"""
        now = _utc_now()
        mock_index_service.delete_case_vector.return_value = DeleteVectorIndexResponse(
            success=True,
            deleted_count=0,
            deleted_at=now,
        )
        resp = await client.post(
            "/api/vector-index/delete",
            json={
                "case_id": "ghost",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_missing_identifiers_returns_422(self, client):
        """未提供 ``case_id``/``vector_id`` 时返回 422。"""
        resp = await client.post(
            "/api/vector-index/delete",
            json={
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_runtime_returns_500(self, client, mock_index_service):
        """删除路径 ``RuntimeError`` 映射为 500。"""
        mock_index_service.delete_case_vector.side_effect = RuntimeError("db down")
        resp = await client.post(
            "/api/vector-index/delete",
            json={
                "case_id": "case_001",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == ErrorCode.INTERNAL_ERROR


class TestVectorSearch:
    """POST ``/api/vector-search``。"""

    @pytest.mark.asyncio
    async def test_search_success_has_items(self, client, mock_search_service):
        """搜索成功返回候选列表。"""
        mock_search_service.search.return_value = VectorSearchResponse(
            items=[_search_candidate("c1")],
            query_metadata=_search_meta(),
        )
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "漏水", "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["case_id"] == "c1"

    @pytest.mark.asyncio
    async def test_search_empty_items(self, client, mock_search_service):
        """仓储无命中时 ``items`` 为空数组。"""
        mock_search_service.search.return_value = VectorSearchResponse(
            items=[],
            query_metadata=_search_meta(total_candidates_considered=0),
        )
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "无命中", "top_k": 10},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.asyncio
    async def test_search_filters_passed_to_service(self, client, mock_search_service):
        """过滤条件透传至 ``VectorSearchService.search``。"""
        await client.post(
            "/api/vector-search",
            json={
                "query_text": "test",
                "top_k": 3,
                "filters": {"brand_id": "brand_x", "store_id": "store_y"},
            },
        )
        mock_search_service.search.assert_awaited_once()
        req = mock_search_service.search.call_args[0][0]
        assert isinstance(req, VectorSearchRequest)
        assert req.filters is not None
        assert req.filters.brand_id == "brand_x"
        assert req.filters.store_id == "store_y"

    @pytest.mark.asyncio
    async def test_search_top_k_zero_returns_422(self, client):
        """``top_k=0`` 违反 schema，返回 422。"""
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "x", "top_k": 0},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_empty_query_text_returns_422(self, client):
        """空 ``query_text`` 由 Pydantic 校验拒绝。"""
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "", "top_k": 5},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_search_whitespace_query_semantic_validation_returns_422(
        self, client, mock_search_service,
    ):
        """仅空白查询文本由服务语义校验返回 422 与 ``fields``。"""
        from app.vector_indexing.search import VectorSearchValidationError

        mock_search_service.search.side_effect = VectorSearchValidationError(
            "query_text",
            "查询文本不能为空",
        )
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "   ", "top_k": 5},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == ErrorCode.VALIDATION_ERROR
        assert detail["fields"]
        assert detail["fields"][0]["field"] == "query_text"

    @pytest.mark.asyncio
    async def test_search_embedding_llm_error_returns_503(
        self, client, mock_search_service,
    ):
        """嵌入依赖抛出 ``LLMClientError`` 时返回 503 与原错误码。"""
        mock_search_service.search.side_effect = LLMClientError(
            ErrorCode.EMBEDDING_TIMEOUT,
            "timeout",
            retryable=True,
        )
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "ok", "top_k": 5},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == ErrorCode.EMBEDDING_TIMEOUT

    @pytest.mark.asyncio
    async def test_search_deleted_case_no_hits_empty_items(
        self, client, mock_search_service,
    ):
        """已删除案例：mock 仓储空候选时 ``items=[]``。"""
        mock_search_service.search.return_value = VectorSearchResponse(
            items=[],
            query_metadata=_search_meta(
                filters_applied={},
                total_candidates_considered=0,
            ),
        )
        resp = await client.post(
            "/api/vector-search",
            json={"query_text": "deleted-case", "top_k": 10},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.asyncio
    async def test_filters_semantic_invalid_tags_returns_422(
        self, client, mock_search_service,
    ):
        """过滤语义非法（如空标签）映射为 422 ``VALIDATION_ERROR``。"""
        from app.vector_indexing.search import VectorSearchValidationError

        mock_search_service.search.side_effect = VectorSearchValidationError(
            "filters.tags",
            "bad",
        )
        resp = await client.post(
            "/api/vector-search",
            json={
                "query_text": "q",
                "top_k": 5,
                "filters": {"tags": [""]},
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == ErrorCode.VALIDATION_ERROR
