"""向量索引可观测性：运维按案例标识查看失败原因（API 契约）。

Requirements: 6.3（HTTP 暴露）、任务 5.3 末句
Boundary: VectorRouter（mock VectorIndexService）
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import ErrorCode
from app.main import app
from app.vector_indexing.schemas import (
    SourceVersion,
    VectorIndexJobResponse,
    VectorIndexStatus,
    VectorIndexStatusResponse,
    VectorJobStatus,
    VectorJobType,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _job_failed(*, error_code: str) -> VectorIndexJobResponse:
    now = _utc_now()
    return VectorIndexJobResponse(
        job_id="job_fail_obs",
        case_id="case_obs",
        job_type=VectorJobType.REFRESH,
        status=VectorJobStatus.FAILED,
        source_version=SourceVersion(case_updated_at=now),
        error_code=error_code,
        error_stage=None,
        retry_count=1,
        started_at=now,
        finished_at=now,
    )


@pytest.fixture
def mock_index_service() -> AsyncMock:
    """Mock ``VectorIndexService``（仅状态接口）。"""
    m = AsyncMock()
    m.get_case_status.return_value = VectorIndexStatusResponse(
        case_id="case_obs",
        status=VectorIndexStatus.FAILED,
        latest_job=_job_failed(error_code=ErrorCode.EMBEDDING_TIMEOUT),
        current_vector=None,
        last_error_code=ErrorCode.EMBEDDING_TIMEOUT,
    )
    return m


@pytest.fixture
def client(mock_index_service):
    """ASGI 客户端：注入向量索引服务 mock。"""
    from app.vector_indexing.router import get_vector_index_service

    app.dependency_overrides[get_vector_index_service] = lambda: mock_index_service

    yield AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_vector_index_status_failed_exposes_last_error_code(client, mock_index_service):
    """最近任务失败时 ``GET /vector-index`` 返回 ``failed`` 与 ``last_error_code``。"""
    mock_index_service.get_case_status.return_value = VectorIndexStatusResponse(
        case_id="case_obs",
        status=VectorIndexStatus.FAILED,
        latest_job=_job_failed(error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR),
        current_vector=None,
        last_error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
    )

    resp = await client.get("/api/a3-cases/case_obs/vector-index")
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "case_obs"
    assert body["status"] == "failed"
    assert body["last_error_code"] == ErrorCode.EMBEDDING_PROVIDER_ERROR
    assert body["latest_job"] is not None
    assert body["latest_job"]["error_code"] == ErrorCode.EMBEDDING_PROVIDER_ERROR
