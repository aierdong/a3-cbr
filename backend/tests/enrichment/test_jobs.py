"""EnrichmentJobRunner 测试。

测试增强运行生命周期管理和重试边界：
- run_enrichment: 创建运行、加载快照、执行增强、返回状态
- retry_run: 重试 retryable 运行、重试次数限制、状态校验
- 失败处理: 快照加载失败、LLM 可重试/不可重试失败、内部错误

Requirements: 1.4, 4.2, 4.4, 6.4
Boundary: EnrichmentJobRunner
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.llm_client import LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.case_snapshot import (
    EnrichmentCaseNotFoundError,
    EnrichmentStateConflictError,
)
from app.enrichment.jobs import EnrichmentJobRunner
from app.enrichment.models import CaseEnrichmentRun
from app.enrichment.schemas import (
    CreateEnrichmentRunRequest,
    EnrichmentRunResponse,
    ErrorStage,
    RequestPurpose,
    RunStatus,
    TaskType,
)
from app.enrichment.validators import OutputValidationException, ValidationErrorCode


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_config(**overrides) -> EnrichmentLLMConfig:
    data = dict(
        api_key="deepseek",
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        timeout_ms=30000,
        max_retries=2,
        privacy_acknowledged=True,
    )
    data.update(overrides)
    return EnrichmentLLMConfig(**data)


def _make_run_orm(
    run_id: str = "run_001",
    case_id: str = "case_001",
    status: RunStatus = RunStatus.RUNNING,
    retry_count: int = 0,
    **overrides,
) -> CaseEnrichmentRun:
    """创建测试用运行记录 ORM 对象。"""
    run = CaseEnrichmentRun()
    run.run_id = run_id
    run.case_id = case_id
    run.task_type = TaskType.CASE_ENRICHMENT
    run.status = status
    run.model_id = "deepseek-v4-flash"
    run.request_purpose = RequestPurpose.CASE_ENRICHMENT
    run.case_updated_at = _make_utc_now()
    run.error_code = overrides.get("error_code")
    run.error_stage = overrides.get("error_stage")
    run.retry_count = retry_count
    run.started_at = _make_utc_now()
    run.finished_at = overrides.get("finished_at")
    return run


def _make_request() -> CreateEnrichmentRunRequest:
    return CreateEnrichmentRunRequest()


def _create_runner(
    enrichment_service=None,
    case_provider=None,
    repository=None,
    config=None,
) -> EnrichmentJobRunner:
    """创建带有 mock 依赖的 EnrichmentJobRunner 实例。"""
    if enrichment_service is None:
        enrichment_service = AsyncMock()
    if case_provider is None:
        case_provider = AsyncMock()
    if repository is None:
        repository = AsyncMock()
    if config is None:
        config = _make_config()

    return EnrichmentJobRunner(
        enrichment_service=enrichment_service,
        case_provider=case_provider,
        repository=repository,
        config=config,
    )


def _setup_repository_for_response(repository, run_orm):
    """设置 repository mock 以支持 _build_run_response。"""
    repository.get_run.return_value = run_orm


# ===========================================================================
# run_enrichment 测试
# ===========================================================================


class TestRunEnrichment:
    """测试 run_enrichment 执行入口。"""

    @pytest.mark.asyncio
    async def test_successful_enrichment_returns_response(self):
        """成功增强应返回 succeeded 状态的响应。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        # execute_enrichment 成功后，运行记录已更新为 succeeded
        succeeded_run = _make_run_orm(
            status=RunStatus.SUCCEEDED,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = succeeded_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.return_value = MagicMock()

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.run_id == "run_001"
        assert response.case_id == "case_001"
        assert response.status == RunStatus.SUCCEEDED
        repository.create_run.assert_called_once()
        case_provider.load_snapshot.assert_called_once_with("case_001")
        enrichment_service.execute_enrichment.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_run_record_with_running_status(self):
        """应创建 status=running 的运行记录。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run
        succeeded_run = _make_run_orm(status=RunStatus.SUCCEEDED)
        repository.get_run.return_value = succeeded_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        await runner.run_enrichment("case_001", _make_request())

        call_args = repository.create_run.call_args[0][0]
        assert call_args.status == RunStatus.RUNNING
        assert call_args.case_id == "case_001"
        assert call_args.task_type == TaskType.CASE_ENRICHMENT
        assert call_args.model_id == "deepseek-v4-flash"
        assert call_args.request_purpose == RequestPurpose.CASE_ENRICHMENT

    @pytest.mark.asyncio
    async def test_case_not_found_marks_run_failed(self):
        """案例不存在应标记运行失败（error_stage=load_case）。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        failed_run = _make_run_orm(
            status=RunStatus.FAILED,
            error_code=ErrorCode.CASE_NOT_FOUND,
            error_stage=ErrorStage.LOAD_CASE,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.side_effect = EnrichmentCaseNotFoundError(
            "case_001"
        )

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.FAILED
        assert response.error_code == ErrorCode.CASE_NOT_FOUND
        repository.fail_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_state_conflict_marks_run_failed(self):
        """draft 状态案例应标记运行失败（error_code=ENRICHMENT_STATE_CONFLICT）。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        failed_run = _make_run_orm(
            status=RunStatus.FAILED,
            error_code=ErrorCode.ENRICHMENT_STATE_CONFLICT,
            error_stage=ErrorStage.LOAD_CASE,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.side_effect = EnrichmentStateConflictError(
            case_id="case_001", current_status="draft"
        )

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.FAILED
        assert response.error_code == ErrorCode.ENRICHMENT_STATE_CONFLICT
        repository.fail_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_retryable_llm_error_marks_run_retryable(self):
        """LLM 可重试错误（超时、限流）应标记运行为 retryable。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        retryable_run = _make_run_orm(
            status=RunStatus.RETRYABLE,
            error_code=ErrorCode.LLM_TIMEOUT,
            error_stage=ErrorStage.LLM_CALL,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = retryable_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="LLM 调用超时",
            retryable=True,
        )

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.RETRYABLE
        assert response.error_code == ErrorCode.LLM_TIMEOUT
        repository.mark_retryable.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_retryable_llm_error_run_stays_failed(self):
        """LLM 不可重试错误应保持 Service 设置的 failed 状态。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        failed_run = _make_run_orm(
            status=RunStatus.FAILED,
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            error_stage=ErrorStage.PARSE,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            message="LLM 响应无法解析",
            retryable=False,
        )

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.FAILED
        # mark_retryable 不应被调用
        repository.mark_retryable.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_run_stays_failed(self):
        """输出校验失败应保持 Service 设置的 failed 状态。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        failed_run = _make_run_orm(
            status=RunStatus.FAILED,
            error_code=ValidationErrorCode.INJECTION_SUSPECTED,
            error_stage=ErrorStage.VALIDATE,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.side_effect = (
            OutputValidationException(
                error_code=ValidationErrorCode.INJECTION_SUSPECTED,
                message="注入嫌疑",
            )
        )

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.FAILED
        repository.fail_run.assert_not_called()
        repository.mark_retryable.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_error_marks_run_failed(self):
        """未预期异常应标记运行失败（INTERNAL_ERROR）。"""
        repository = AsyncMock()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        failed_run = _make_run_orm(
            status=RunStatus.FAILED,
            error_code=ErrorCode.INTERNAL_ERROR,
            error_stage=ErrorStage.PERSIST,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.side_effect = RuntimeError(
            "数据库连接失败"
        )

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert response.status == RunStatus.FAILED
        assert response.error_code == ErrorCode.INTERNAL_ERROR
        repository.fail_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_call_execute_enrichment_on_snapshot_failure(self):
        """快照加载失败时不应调用 execute_enrichment。"""
        repository = AsyncMock()
        repository.create_run.return_value = _make_run_orm()
        repository.get_run.return_value = _make_run_orm(status=RunStatus.FAILED)

        case_provider = AsyncMock()
        case_provider.load_snapshot.side_effect = EnrichmentCaseNotFoundError(
            "case_001"
        )

        enrichment_service = AsyncMock()

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        await runner.run_enrichment("case_001", _make_request())

        enrichment_service.execute_enrichment.assert_not_called()

    @pytest.mark.asyncio
    async def test_response_includes_all_fields(self):
        """响应应包含所有必需字段。"""
        repository = AsyncMock()
        now = _make_utc_now()
        created_run = _make_run_orm(status=RunStatus.RUNNING)
        repository.create_run.return_value = created_run

        full_run = _make_run_orm(
            status=RunStatus.SUCCEEDED,
            finished_at=now,
        )
        full_run.started_at = now
        repository.get_run.return_value = full_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        response = await runner.run_enrichment("case_001", _make_request())

        assert isinstance(response, EnrichmentRunResponse)
        assert response.run_id is not None
        assert response.case_id == "case_001"
        assert response.task_type == TaskType.CASE_ENRICHMENT
        assert response.model_id == "deepseek-v4-flash"
        assert response.request_purpose == RequestPurpose.CASE_ENRICHMENT
        assert response.retry_count >= 0


# ===========================================================================
# retry_run 测试
# ===========================================================================


class TestRetryRun:
    """测试 retry_run 重试入口。"""

    @pytest.mark.asyncio
    async def test_retry_retryable_run_succeeds(self):
        """重试 retryable 运行应创建新运行记录并执行增强。"""
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            error_code=ErrorCode.LLM_TIMEOUT,
            error_stage=ErrorStage.LLM_CALL,
            retry_count=0,
            finished_at=_make_utc_now(),
        )
        repository.get_run.side_effect = [
            original_run,  # retry_run 获取原运行
            _make_run_orm(run_id="run_new", status=RunStatus.RUNNING),  # create_run 后查询
            _make_run_orm(run_id="run_new", status=RunStatus.SUCCEEDED),  # _build_run_response
        ]

        new_run = _make_run_orm(run_id="run_new", status=RunStatus.RUNNING)
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.retry_run("run_original")

        assert response.run_id == "run_new"
        repository.create_run.assert_called_once()
        case_provider.load_snapshot.assert_called_once_with("case_001")
        enrichment_service.execute_enrichment.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_increments_retry_count(self):
        """重试应递增 retry_count。"""
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            retry_count=1,
            finished_at=_make_utc_now(),
        )
        repository.get_run.side_effect = [
            original_run,
            _make_run_orm(run_id="run_new", retry_count=2),
            _make_run_orm(run_id="run_new", status=RunStatus.SUCCEEDED),
        ]

        new_run = _make_run_orm(run_id="run_new")
        new_run.retry_count = 2
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        await runner.retry_run("run_original")

        create_call = repository.create_run.call_args[0][0]
        assert create_call.case_id == "case_001"

    @pytest.mark.asyncio
    async def test_retry_non_retryable_run_raises(self):
        """重试非 retryable 状态的运行应抛出 ValueError。"""
        repository = AsyncMock()

        failed_run = _make_run_orm(
            run_id="run_failed",
            status=RunStatus.FAILED,
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = failed_run

        runner = _create_runner(repository=repository)

        with pytest.raises(ValueError, match="当前状态不允许重试"):
            await runner.retry_run("run_failed")

    @pytest.mark.asyncio
    async def test_retry_succeeded_run_raises(self):
        """重试 succeeded 状态的运行应抛出 ValueError。"""
        repository = AsyncMock()

        succeeded_run = _make_run_orm(
            run_id="run_succeeded",
            status=RunStatus.SUCCEEDED,
            finished_at=_make_utc_now(),
        )
        repository.get_run.return_value = succeeded_run

        runner = _create_runner(repository=repository)

        with pytest.raises(ValueError, match="当前状态不允许重试"):
            await runner.retry_run("run_succeeded")

    @pytest.mark.asyncio
    async def test_retry_running_run_raises(self):
        """重试 running 状态的运行应抛出 ValueError。"""
        repository = AsyncMock()

        running_run = _make_run_orm(
            run_id="run_running",
            status=RunStatus.RUNNING,
        )
        repository.get_run.return_value = running_run

        runner = _create_runner(repository=repository)

        with pytest.raises(ValueError, match="当前状态不允许重试"):
            await runner.retry_run("run_running")

    @pytest.mark.asyncio
    async def test_retry_nonexistent_run_raises(self):
        """重试不存在的运行应抛出 ValueError。"""
        repository = AsyncMock()
        repository.get_run.return_value = None

        runner = _create_runner(repository=repository)

        with pytest.raises(ValueError, match="重试目标运行不存在"):
            await runner.retry_run("nonexistent_run")

    @pytest.mark.asyncio
    async def test_retry_exceeds_max_retries_marks_failed(self):
        """超过最大重试次数应标记原运行失败。"""
        config = _make_config(max_retries=2)
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            retry_count=2,  # 已达 max_retries
            finished_at=_make_utc_now(),
        )
        failed_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.FAILED,
            error_code=ErrorCode.ENRICHMENT_RETRY_NOT_ALLOWED,
            finished_at=_make_utc_now(),
        )
        repository.get_run.side_effect = [original_run, failed_run]

        runner = _create_runner(
            repository=repository,
            config=config,
        )

        response = await runner.retry_run("run_original")

        assert response.status == RunStatus.FAILED
        assert response.error_code == ErrorCode.ENRICHMENT_RETRY_NOT_ALLOWED
        # 不应创建新运行记录
        repository.create_run.assert_not_called()
        # 应标记原运行失败
        repository.fail_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_within_limit_creates_new_run(self):
        """未达最大重试次数时应创建新运行记录。"""
        config = _make_config(max_retries=2)
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            retry_count=1,  # < max_retries
            finished_at=_make_utc_now(),
        )
        new_run = _make_run_orm(run_id="run_new", status=RunStatus.RUNNING)
        succeeded_run = _make_run_orm(
            run_id="run_new", status=RunStatus.SUCCEEDED,
        )

        repository.get_run.side_effect = [
            original_run,
            new_run,
            succeeded_run,
        ]
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
            config=config,
        )

        response = await runner.retry_run("run_original")

        assert response.run_id == "run_new"
        repository.create_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_preserves_case_id_and_updated_at(self):
        """重试应保留原运行的 case_id 和 case_updated_at。"""
        repository = AsyncMock()

        case_updated = _make_utc_now()
        original_run = _make_run_orm(
            run_id="run_original",
            case_id="case_002",
            status=RunStatus.RETRYABLE,
            retry_count=0,
            finished_at=_make_utc_now(),
        )
        original_run.case_updated_at = case_updated

        new_run = _make_run_orm(run_id="run_new", case_id="case_002")
        new_run.case_updated_at = case_updated

        repository.get_run.side_effect = [
            original_run,
            new_run,
            _make_run_orm(run_id="run_new", status=RunStatus.SUCCEEDED),
        ]
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        await runner.retry_run("run_original")

        create_call = repository.create_run.call_args[0][0]
        assert create_call.case_id == "case_002"
        assert create_call.case_updated_at == case_updated

    @pytest.mark.asyncio
    async def test_retry_snapshot_failure_marks_new_run_failed(self):
        """重试时快照加载失败应标记新运行失败。"""
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            retry_count=0,
            finished_at=_make_utc_now(),
        )
        new_run = _make_run_orm(run_id="run_new", status=RunStatus.RUNNING)
        failed_new_run = _make_run_orm(
            run_id="run_new", status=RunStatus.FAILED,
        )

        repository.get_run.side_effect = [
            original_run,
            new_run,
            failed_new_run,
        ]
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.side_effect = EnrichmentCaseNotFoundError(
            "case_001"
        )

        runner = _create_runner(
            repository=repository,
            case_provider=case_provider,
        )

        response = await runner.retry_run("run_original")

        assert response.run_id == "run_new"
        repository.fail_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_retryable_llm_error_marks_new_run_retryable(self):
        """重试时 LLM 可重试错误应标记新运行为 retryable。"""
        repository = AsyncMock()

        original_run = _make_run_orm(
            run_id="run_original",
            status=RunStatus.RETRYABLE,
            retry_count=0,
            finished_at=_make_utc_now(),
        )
        new_run = _make_run_orm(run_id="run_new", status=RunStatus.RUNNING)
        # The final _build_run_response should see the RETRYABLE status
        # (after mark_retryable is called).
        retryable_new_run = _make_run_orm(
            run_id="run_new", status=RunStatus.RETRYABLE,
        )

        # get_run is called twice:
        # 1st: get_run("run_original") for validation
        # 2nd: get_run(new_run_id) in _build_run_response
        def _get_run_side_effect(rid):
            if rid == "run_original":
                return original_run
            return retryable_new_run

        repository.get_run.side_effect = _get_run_side_effect
        repository.create_run.return_value = new_run

        case_provider = AsyncMock()
        case_provider.load_snapshot.return_value = MagicMock()

        enrichment_service = AsyncMock()
        enrichment_service.execute_enrichment.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_RATE_LIMITED,
            message="LLM 限流",
            retryable=True,
        )

        runner = _create_runner(
            enrichment_service=enrichment_service,
            case_provider=case_provider,
            repository=repository,
        )

        response = await runner.retry_run("run_original")

        assert response.status == RunStatus.RETRYABLE
        repository.mark_retryable.assert_called_once()
