"""案例增强 API 测试。

测试 EnrichmentRouter 的 4 个端点：
- POST /api/a3-cases/{case_id}/enrichment-runs
- GET  /api/a3-cases/{case_id}/enrichment
- POST /api/enrichment/delete
- POST /api/enrichment-runs/{run_id}/retry

覆盖成功路径、错误路径、幂等性和边界条件。

Requirements: 1.1, 1.2, 1.3, 1.4, 4.4, 4.5, 6.4, 7.1, 7.3, 7.5
Boundary: EnrichmentRouter
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    EnrichmentRunResponse,
    ErrorStage,
    RequestPurpose,
    RunStatus,
    TaskType,
)
from app.main import app


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_run_response(
    run_id: str = "run_001",
    case_id: str = "case_001",
    status: RunStatus = RunStatus.RUNNING,
    error_code: str | None = None,
    error_stage: ErrorStage | None = None,
    retry_count: int = 0,
) -> EnrichmentRunResponse:
    now = _make_utc_now()
    return EnrichmentRunResponse(
        run_id=run_id,
        case_id=case_id,
        task_type=TaskType.CASE_ENRICHMENT,
        status=status,
        model_id="deepseek-v4-pro",
        request_purpose=RequestPurpose.CASE_ENRICHMENT,
        case_updated_at=now,
        error_code=error_code,
        error_stage=error_stage,
        retry_count=retry_count,
        started_at=now,
        finished_at=now if status != RunStatus.RUNNING else None,
    )


def _make_mock_job_runner() -> AsyncMock:
    mock = AsyncMock()
    mock.run_enrichment.return_value = _make_run_response()
    mock.retry_run.return_value = _make_run_response(
        run_id="run_retry_001", status=RunStatus.RUNNING,
    )
    return mock


def _make_mock_service() -> AsyncMock:
    mock = AsyncMock()
    mock.delete_enrichment_data.return_value = AsyncMock(
        success=True,
        deleted_count=2,
        deleted_at=_make_utc_now(),
    )
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_job_runner():
    """提供 mock EnrichmentJobRunner。"""
    return _make_mock_job_runner()


@pytest.fixture
def mock_service():
    """提供 mock EnrichmentService。"""
    return _make_mock_service()


@pytest.fixture
def client(mock_job_runner, mock_service):
    """测试客户端，注入 mock 依赖。"""
    from app.enrichment.router import (
        get_enrichment_job_runner,
        get_enrichment_service,
    )

    app.dependency_overrides[get_enrichment_job_runner] = (
        lambda: mock_job_runner
    )
    app.dependency_overrides[get_enrichment_service] = (
        lambda: mock_service
    )

    yield AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    app.dependency_overrides.clear()


# ===========================================================================
# POST /api/a3-cases/{case_id}/enrichment-runs
# ===========================================================================


class TestCreateEnrichmentRun:
    """测试创建增强运行端点。"""

    @pytest.mark.asyncio
    async def test_create_returns_200_with_running_status(
        self, client, mock_job_runner,
    ):
        """成功创建应返回 HTTP 200 和 running 状态。"""
        mock_job_runner.run_enrichment.return_value = _make_run_response(
            status=RunStatus.RUNNING,
        )

        response = await client.post(
            "/api/a3-cases/case_001/enrichment-runs",
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run_001"
        assert data["case_id"] == "case_001"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_create_delegates_to_job_runner(
        self, client, mock_job_runner,
    ):
        """应委托给 EnrichmentJobRunner.run_enrichment。"""
        await client.post(
            "/api/a3-cases/case_001/enrichment-runs",
            json={},
        )

        mock_job_runner.run_enrichment.assert_called_once()
        call_args = mock_job_runner.run_enrichment.call_args
        assert call_args[0][0] == "case_001"

    @pytest.mark.asyncio
    async def test_create_response_includes_all_required_fields(
        self, client, mock_job_runner,
    ):
        """响应应包含所有必需字段。"""
        now = _make_utc_now()
        mock_job_runner.run_enrichment.return_value = EnrichmentRunResponse(
            run_id="run_full",
            case_id="case_001",
            task_type=TaskType.CASE_ENRICHMENT,
            status=RunStatus.SUCCEEDED,
            model_id="deepseek-v4-pro",
            request_purpose=RequestPurpose.CASE_ENRICHMENT,
            case_updated_at=now,
            error_code=None,
            error_stage=None,
            retry_count=0,
            started_at=now,
            finished_at=now,
        )

        response = await client.post(
            "/api/a3-cases/case_001/enrichment-runs",
            json={},
        )

        data = response.json()
        assert "run_id" in data
        assert "case_id" in data
        assert "task_type" in data
        assert "status" in data
        assert "model_id" in data
        assert "request_purpose" in data
        assert "case_updated_at" in data
        assert "retry_count" in data
        assert "started_at" in data

    @pytest.mark.asyncio
    async def test_create_with_failed_status(
        self, client, mock_job_runner,
    ):
        """案例不存在时应返回 failed 状态（不抛 HTTP 异常）。"""
        mock_job_runner.run_enrichment.return_value = _make_run_response(
            status=RunStatus.FAILED,
            error_code=ErrorCode.CASE_NOT_FOUND,
            error_stage=ErrorStage.LOAD_CASE,
        )

        response = await client.post(
            "/api/a3-cases/nonexistent/enrichment-runs",
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error_code"] == ErrorCode.CASE_NOT_FOUND


# ===========================================================================
# GET /api/a3-cases/{case_id}/enrichment
# ===========================================================================


class TestGetEnrichmentStatus:
    """测试查询增强状态端点。"""

    @pytest.mark.asyncio
    async def test_status_returns_200_with_empty_state(
        self, client, mock_service,
    ):
        """无增强数据时应返回空状态。"""
        from app.enrichment.repository import EnrichmentRepository

        # 覆盖依赖：需要真实的 repository 查询
        mock_repo = AsyncMock()
        mock_repo.get_latest_run.return_value = None
        mock_repo.get_current_result.return_value = None

        def _override_service():
            svc = AsyncMock()
            svc.delete_enrichment_data = mock_service.delete_enrichment_data
            return svc

        # 直接覆盖 get_db 以注入 mock repository
        from app.db.session import get_db

        mock_session = AsyncMock()

        async def _override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = _override_get_db

        # 使用 mock repository
        original_repo_init = EnrichmentRepository.__init__

        def _mock_init(self, db):
            self._db = mock_session
            # 复制 mock 的方法
            self.get_latest_run = mock_repo.get_latest_run
            self.get_current_result = mock_repo.get_current_result

        EnrichmentRepository.__init__ = _mock_init

        try:
            response = await client.get(
                "/api/a3-cases/case_001/enrichment",
            )

            assert response.status_code == 200
            data = response.json()
            assert data["case_id"] == "case_001"
            assert data["latest_run"] is None
            assert data["current_result"] is None
        finally:
            EnrichmentRepository.__init__ = original_repo_init
            app.dependency_overrides.clear()


# ===========================================================================
# POST /api/enrichment/delete
# ===========================================================================


class TestDeleteEnrichment:
    """测试删除增强数据端点。"""

    @pytest.mark.asyncio
    async def test_delete_returns_200_on_success(
        self, client, mock_service,
    ):
        """成功删除应返回 HTTP 200 和删除结果。"""
        mock_service.delete_enrichment_data.return_value = AsyncMock(
            success=True,
            deleted_count=3,
            deleted_at=_make_utc_now(),
        )

        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 3
        assert "deleted_at" in data

    @pytest.mark.asyncio
    async def test_delete_idempotent_for_nonexistent_data(
        self, client, mock_service,
    ):
        """对不存在的派生数据应返回 deleted_count: 0（幂等）。"""
        mock_service.delete_enrichment_data.return_value = AsyncMock(
            success=True,
            deleted_count=0,
            deleted_at=_make_utc_now(),
        )

        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "nonexistent_case",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_by_enrichment_id(
        self, client, mock_service,
    ):
        """应支持按 enrichment_id 删除。"""
        mock_service.delete_enrichment_data.return_value = AsyncMock(
            success=True,
            deleted_count=2,
            deleted_at=_make_utc_now(),
        )

        response = await client.post(
            "/api/enrichment/delete",
            json={
                "enrichment_id": "enrichment_001",
                "reason": "enrichment_deleted",
                "requested_by": "anonymous_user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_delete_without_ids_returns_422(self, client):
        """未提供 case_id 或 enrichment_id 应返回 422。"""
        response = await client.post(
            "/api/enrichment/delete",
            json={
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_missing_reason_returns_422(self, client):
        """缺少 reason 字段应返回 422。"""
        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "requested_by": "system",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_missing_requested_by_returns_422(self, client):
        """缺少 requested_by 字段应返回 422。"""
        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "reason": "case_deleted",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_invalid_reason_returns_422(self, client):
        """无效的 reason 值应返回 422。"""
        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "reason": "invalid_reason",
                "requested_by": "system",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_service_failure_returns_500(
        self, client, mock_service,
    ):
        """服务层抛出异常应返回 500。"""
        mock_service.delete_enrichment_data.side_effect = RuntimeError(
            "数据库连接失败"
        )

        response = await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "reason": "case_deleted",
                "requested_by": "system",
            },
        )

        assert response.status_code == 500
        data = response.json()
        assert data["detail"]["code"] == ErrorCode.INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_delete_calls_service_with_correct_params(
        self, client, mock_service,
    ):
        """应将正确的参数传递给 service。"""
        await client.post(
            "/api/enrichment/delete",
            json={
                "case_id": "case_001",
                "enrichment_id": "enrichment_001",
                "reason": "enrichment_deleted",
                "requested_by": "system",
            },
        )

        mock_service.delete_enrichment_data.assert_called_once_with(
            case_id="case_001",
            enrichment_id="enrichment_001",
        )


# ===========================================================================
# POST /api/enrichment-runs/{run_id}/retry
# ===========================================================================


class TestRetryEnrichmentRun:
    """测试重试增强运行端点。"""

    @pytest.mark.asyncio
    async def test_retry_returns_200_on_success(
        self, client, mock_job_runner,
    ):
        """成功重试应返回 HTTP 200 和新运行记录。"""
        mock_job_runner.retry_run.return_value = _make_run_response(
            run_id="run_retry_001",
            status=RunStatus.RUNNING,
        )

        response = await client.post(
            "/api/enrichment-runs/run_001/retry",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run_retry_001"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_retry_delegates_to_job_runner(
        self, client, mock_job_runner,
    ):
        """应委托给 EnrichmentJobRunner.retry_run。"""
        await client.post(
            "/api/enrichment-runs/run_001/retry",
        )

        mock_job_runner.retry_run.assert_called_once_with("run_001")

    @pytest.mark.asyncio
    async def test_retry_nonexistent_run_returns_404(
        self, client, mock_job_runner,
    ):
        """重试不存在的运行应返回 404。"""
        mock_job_runner.retry_run.side_effect = ValueError(
            "重试目标运行不存在: run_id=nonexistent"
        )

        response = await client.post(
            "/api/enrichment-runs/nonexistent/retry",
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["code"] == ErrorCode.ENRICHMENT_RUN_NOT_FOUND

    @pytest.mark.asyncio
    async def test_retry_non_retryable_run_returns_409(
        self, client, mock_job_runner,
    ):
        """重试非 retryable 状态的运行应返回 409。"""
        mock_job_runner.retry_run.side_effect = ValueError(
            "当前状态不允许重试: run_id=run_001, status=succeeded"
        )

        response = await client.post(
            "/api/enrichment-runs/run_001/retry",
        )

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["code"] == ErrorCode.ENRICHMENT_RETRY_NOT_ALLOWED

    @pytest.mark.asyncio
    async def test_retry_response_includes_new_run_id(
        self, client, mock_job_runner,
    ):
        """重试响应应包含新的 run_id。"""
        mock_job_runner.retry_run.return_value = _make_run_response(
            run_id="run_new_002",
            status=RunStatus.RUNNING,
        )

        response = await client.post(
            "/api/enrichment-runs/run_001/retry",
        )

        data = response.json()
        assert data["run_id"] == "run_new_002"
