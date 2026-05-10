"""向量索引任务生命周期与手动重试编排。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode
from app.vector_indexing.models import EmbeddingJobStatus, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.schemas import RefreshVectorIndexRequest, VectorIndexJobResponse


class VectorIndexJobNotFoundError(Exception):
    """指定 ``job_id`` 的任务不存在。"""

    def __init__(self, job_id: str) -> None:
        """初始化异常。"""
        self.job_id = job_id
        super().__init__(job_id)


class VectorJobRetryNotAllowedError(Exception):
    """当前任务状态或错误类型不允许重试。"""

    def __init__(self, error_code: str) -> None:
        """初始化异常。"""
        self.error_code = error_code
        super().__init__(error_code)


def embedding_failure_retryable(code: str | None) -> bool:
    """超时、限流与供应商错误允许进入 RETRYABLE / 手动重试路径。"""
    if not code:
        return False
    return code in (
        ErrorCode.EMBEDDING_TIMEOUT,
        ErrorCode.EMBEDDING_RATE_LIMITED,
        ErrorCode.EMBEDDING_PROVIDER_ERROR,
    )


class VectorJobRunner:
    """校验重试资格并委托 ``VectorIndexService`` 执行强制刷新。"""

    def __init__(
        self,
        db: AsyncSession,
        index_service: object,
        *,
        max_manual_retries: int,
    ) -> None:
        """初始化 Runner。

        Args:
            db: 异步会话。
            index_service: ``VectorIndexService`` 实例（避免循环导入标注为 object）。
            max_manual_retries: 任务级允许的最大 ``retry_count``（达到后拒绝再重试）。
        """
        self._svc = index_service
        self._repo = VectorRepository(db)
        self._max_manual_retries = max_manual_retries

    async def retry_job(self, job_id: str) -> VectorIndexJobResponse:
        """对失败或可重试任务发起一次新的强制刷新。

        Args:
            job_id: 历史任务标识。

        Returns:
            新刷新任务的响应。

        Raises:
            VectorIndexJobNotFoundError: 任务不存在。
            VectorJobRetryNotAllowedError: 状态或错误码不允许重试。
        """
        prior = await self._repo.get_job_by_id(job_id)
        if prior is None:
            raise VectorIndexJobNotFoundError(job_id)

        if prior.job_type not in (
            VectorIndexJobType.REFRESH.value,
            VectorIndexJobType.INDEX.value,
            VectorIndexJobType.RETRY.value,
        ):
            raise VectorJobRetryNotAllowedError(ErrorCode.VECTOR_RETRY_NOT_ALLOWED)

        if prior.status in (
            EmbeddingJobStatus.QUEUED.value,
            EmbeddingJobStatus.RUNNING.value,
        ):
            raise VectorJobRetryNotAllowedError(ErrorCode.VECTOR_STATE_CONFLICT)

        if prior.status not in (
            EmbeddingJobStatus.FAILED.value,
            EmbeddingJobStatus.RETRYABLE.value,
        ):
            raise VectorJobRetryNotAllowedError(ErrorCode.VECTOR_RETRY_NOT_ALLOWED)

        if prior.status == EmbeddingJobStatus.FAILED.value:
            if not embedding_failure_retryable(prior.error_code):
                raise VectorJobRetryNotAllowedError(ErrorCode.VECTOR_RETRY_NOT_ALLOWED)

        if prior.retry_count >= self._max_manual_retries:
            raise VectorJobRetryNotAllowedError(ErrorCode.VECTOR_RETRY_NOT_ALLOWED)

        refresh = getattr(self._svc, "refresh_case_index")
        return await refresh(
            prior.case_id,
            RefreshVectorIndexRequest(
                force_rebuild=True,
                carry_retry_count=prior.retry_count + 1,
            ),
        )
