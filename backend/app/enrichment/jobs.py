"""增强运行生命周期管理和重试边界。

为增强运行提供执行入口（同步执行，API 返回运行状态）、
状态返回和可重试失败的重试入口。

Router -> JobRunner -> Service 单向调用链。
JobRunner 负责：创建运行记录、加载快照、委托 Service 执行、
管理运行状态流转、重试入口。

Requirements: 1.4, 4.2, 4.4, 6.4
Boundary: EnrichmentJobRunner
"""

import logging
import uuid

from app.common.llm_client import LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.case_snapshot import (
    CaseSnapshotProvider,
    EnrichmentCaseNotFoundError,
    EnrichmentStateConflictError,
)
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import (
    CreateEnrichmentRunRequest,
    EnrichmentErrorData,
    EnrichmentRunCreate,
    EnrichmentRunResponse,
    ErrorStage,
    RequestPurpose,
    RunStatus,
    TaskType,
)
from app.enrichment.service import EnrichmentService
from app.enrichment.validators import OutputValidationException

logger = logging.getLogger(__name__)


class EnrichmentJobRunner:
    """增强运行生命周期管理。

    职责：
    - 创建 CaseEnrichmentRun 记录
    - 调用 CaseSnapshotProvider.load_snapshot
    - 委托 EnrichmentService.execute_enrichment
    - 管理运行状态流转 (running -> succeeded/failed/retryable)
    - 重试入口（仅允许 retryable 状态，递增 retry_count）

    MVP 阶段同步执行，API 返回运行状态。
    """

    def __init__(
        self,
        enrichment_service: EnrichmentService,
        case_provider: CaseSnapshotProvider,
        repository: EnrichmentRepository,
        config: EnrichmentLLMConfig,
    ) -> None:
        """初始化 JobRunner。

        Args:
            enrichment_service: 增强服务。
            case_provider: 案例快照读取器。
            repository: 增强数据仓储。
            config: LLM 增强配置。
        """
        self._service = enrichment_service
        self._case_provider = case_provider
        self._repository = repository
        self._config = config

    async def run_enrichment(
        self,
        case_id: str,
        request: CreateEnrichmentRunRequest,
    ) -> EnrichmentRunResponse:
        """执行增强运行。

        MVP 阶段同步执行：创建运行记录、加载快照、
        委托 Service 执行增强、返回运行响应。

        任何阶段失败均通过 repository 记录失败信息，
        不抛出异常（调用方始终收到 EnrichmentRunResponse）。

        Args:
            case_id: 案例标识。
            request: 触发增强运行请求。

        Returns:
            增强运行响应，包含 run_id 和最终状态。
        """
        run_id = str(uuid.uuid4())
        now = self._now_utc()

        # 1. 创建运行记录（status=running）
        run_create = EnrichmentRunCreate(
            run_id=run_id,
            case_id=case_id,
            task_type=TaskType.CASE_ENRICHMENT,
            status=RunStatus.RUNNING,
            model_id=self._config.model_id,
            request_purpose=RequestPurpose.CASE_ENRICHMENT,
            case_updated_at=now,
        )
        await self._repository.create_run(run_create)

        # 2. 加载案例快照
        try:
            snapshot = await self._case_provider.load_snapshot(case_id)
        except EnrichmentCaseNotFoundError as exc:
            return await self._handle_snapshot_error(
                run_id, case_id, exc,
                error_code=ErrorCode.CASE_NOT_FOUND,
                error_stage=ErrorStage.LOAD_CASE,
            )
        except EnrichmentStateConflictError as exc:
            return await self._handle_snapshot_error(
                run_id, case_id, exc,
                error_code=ErrorCode.ENRICHMENT_STATE_CONFLICT,
                error_stage=ErrorStage.LOAD_CASE,
            )

        # 3. 委托 Service 执行增强
        #    Service 内部已处理 LLM/校验/持久化失败（fail_run 或 mark_retryable）
        try:
            await self._service.execute_enrichment(snapshot, run_id)
        except LLMClientError as exc:
            if exc.retryable:
                await self._mark_run_retryable(run_id, exc)
            # 非 retryable 时 Service 已调用 fail_run，无需额外处理
        except OutputValidationException:
            # Service 已调用 fail_run，无需额外处理
            pass
        except Exception as exc:
            logger.error(
                "增强执行异常: case_id=%s, run_id=%s, error=%s",
                case_id, run_id, str(exc),
            )
            error = EnrichmentErrorData(
                error_code=ErrorCode.INTERNAL_ERROR,
                error_stage=ErrorStage.PERSIST,
            )
            await self._repository.fail_run(run_id, error)

        # 4. 返回运行响应
        return await self._build_run_response(run_id)

    async def retry_run(self, run_id: str) -> EnrichmentRunResponse:
        """重试已失败的增强运行。

        仅允许 retryable 状态的运行进行重试。
        创建新的运行记录（递增 retry_count），重新执行增强。

        Args:
            run_id: 待重试的运行标识。

        Returns:
            新运行的增强运行响应。

        Raises:
            ValueError: 运行不存在或状态不允许重试。
        """
        # 1. 获取原运行记录
        original_run = await self._repository.get_run(run_id)
        if original_run is None:
            raise ValueError(
                f"重试目标运行不存在: run_id={run_id}"
            )

        # 2. 检查是否可重试
        if original_run.status != RunStatus.RETRYABLE:
            raise ValueError(
                f"当前状态不允许重试: run_id={run_id}, "
                f"status={original_run.status}"
            )

        # 3. 检查重试次数
        if original_run.retry_count >= self._config.max_retries:
            error = EnrichmentErrorData(
                error_code=ErrorCode.ENRICHMENT_RETRY_NOT_ALLOWED,
                error_stage=ErrorStage.LLM_CALL,
            )
            await self._repository.fail_run(run_id, error)
            return await self._build_run_response(run_id)

        # 4. 创建新运行记录（递增 retry_count）
        new_run_id = str(uuid.uuid4())
        run_create = EnrichmentRunCreate(
            run_id=new_run_id,
            case_id=original_run.case_id,
            task_type=TaskType.CASE_ENRICHMENT,
            status=RunStatus.RUNNING,
            model_id=self._config.model_id,
            request_purpose=RequestPurpose.CASE_ENRICHMENT,
            case_updated_at=original_run.case_updated_at,
        )
        new_run = await self._repository.create_run(run_create)
        # 手动设置 retry_count（EnrichmentRunCreate 不含此字段）
        new_run.retry_count = original_run.retry_count + 1
        await self._repository._db.flush()

        # 5. 加载快照并执行增强
        try:
            snapshot = await self._case_provider.load_snapshot(
                original_run.case_id,
            )
        except (EnrichmentCaseNotFoundError, EnrichmentStateConflictError):
            error = EnrichmentErrorData(
                error_code=ErrorCode.CASE_NOT_FOUND,
                error_stage=ErrorStage.LOAD_CASE,
            )
            await self._repository.fail_run(new_run_id, error)
            return await self._build_run_response(new_run_id)

        try:
            await self._service.execute_enrichment(snapshot, new_run_id)
        except LLMClientError as exc:
            if exc.retryable:
                await self._mark_run_retryable(new_run_id, exc)
        except OutputValidationException:
            pass
        except Exception as exc:
            logger.error(
                "重试执行异常: original_run_id=%s, new_run_id=%s, error=%s",
                run_id, new_run_id, str(exc),
            )
            error = EnrichmentErrorData(
                error_code=ErrorCode.INTERNAL_ERROR,
                error_stage=ErrorStage.PERSIST,
            )
            await self._repository.fail_run(new_run_id, error)

        return await self._build_run_response(new_run_id)

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    async def _handle_snapshot_error(
        self,
        run_id: str,
        case_id: str,
        exc: Exception,
        *,
        error_code: str,
        error_stage: ErrorStage,
    ) -> EnrichmentRunResponse:
        """处理快照加载失败：标记运行失败并返回响应。"""
        logger.warning(
            "快照加载失败: case_id=%s, run_id=%s, error=%s",
            case_id, run_id, str(exc),
        )
        error = EnrichmentErrorData(
            error_code=error_code,
            error_stage=error_stage,
        )
        await self._repository.fail_run(run_id, error)
        return await self._build_run_response(run_id)

    async def _mark_run_retryable(
        self,
        run_id: str,
        exc: LLMClientError,
    ) -> None:
        """标记运行为可重试（供应商或临时失败）。"""
        error_stage = EnrichmentService._map_llm_error_stage(exc.error_code)
        error = EnrichmentErrorData(
            error_code=exc.error_code,
            error_stage=error_stage,
        )
        await self._repository.mark_retryable(run_id, error)

    async def _build_run_response(self, run_id: str) -> EnrichmentRunResponse:
        """从仓储构建运行响应。"""
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"运行记录不存在: {run_id}")
        return EnrichmentRunResponse.model_validate(run)

    @staticmethod
    def _now_utc():
        """返回当前 UTC 时间。"""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)
