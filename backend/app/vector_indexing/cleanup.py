"""孤立向量数据后台清理（case-vector-indexing 3.5）。

定期扫描 ``case_vectors``：案例不在 ``a3_cases``，或 ``enrichment_id`` 非空但不在
``case_enrichment_results`` 时，按案例物理删除向量并写入 ``job_type=remove`` 审计行。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import A3Case
from app.enrichment.models import CaseEnrichmentResult
from app.vector_indexing.index_service import _case_vector_audit_hash
from app.vector_indexing.models import CaseVector, EmbeddingJobStatus, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import VectorIndexJobCreate
from app.vector_indexing.schemas import DeleteVectorIndexReason

logger = logging.getLogger(__name__)


class VectorCleanupService:
    """按配置间隔扫描并清理孤立 ``case_vectors`` 行。"""

    def __init__(
        self,
        db_session_factory: Callable[[], AsyncSession],
        *,
        interval_seconds: int = 86400,
        batch_size: int = 500,
        enabled: bool = True,
    ) -> None:
        """初始化向量清理服务。

        Args:
            db_session_factory: 异步会话工厂（每次清理周期新建会话）。
            interval_seconds: 周期间隔（秒）。
            batch_size: 每轮扫描的案例标识上限。
            enabled: 为 ``False`` 时不启动周期循环。

        Returns:
            ``None``。
        """
        self._session_factory = db_session_factory
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._enabled = enabled
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def run_periodic(self) -> None:
        """后台周期入口：失败记录日志并在下一周期重试。

        Args:
            无。

        Returns:
            ``None``。
        """
        if not self._enabled:
            logger.info("向量清理服务已禁用，跳过启动")
            return

        logger.info(
            "向量清理服务启动: interval=%ds, batch_size=%d",
            self._interval_seconds,
            self._batch_size,
        )

        while not self._stop_event.is_set():
            try:
                deleted = await self.cleanup_orphan_vectors()
                if deleted > 0:
                    logger.info("向量孤立清理本轮删除向量数: %d", deleted)
            except Exception:
                logger.exception("向量孤立清理失败，下一周期重试")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(self._interval_seconds),
                )
                break
            except asyncio.TimeoutError:
                continue

        logger.info("向量清理服务已停止")

    async def cleanup_orphan_vectors(
        self,
        *,
        session: AsyncSession | None = None,
    ) -> int:
        """执行一轮孤立向量清理。

        Args:
            session: 可选外部会话（测试注入）；缺省时由工厂创建并在结束时关闭。

        Returns:
            本轮物理删除的向量行数。
        """
        ext_session = session
        owned = ext_session is None
        session = ext_session or self._session_factory()
        total = 0
        try:
            while True:
                case_ids = await self._select_orphan_case_ids(session, self._batch_size)
                if not case_ids:
                    break
                for cid in case_ids:
                    total += await self._purge_orphan_case(session, cid)
                await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if owned:
                await session.close()

        return total

    async def _select_orphan_case_ids(self, session: AsyncSession, limit: int) -> list[str]:
        stmt = (
            select(CaseVector.case_id)
            .outerjoin(A3Case, CaseVector.case_id == A3Case.case_id)
            .outerjoin(
                CaseEnrichmentResult,
                CaseEnrichmentResult.enrichment_id == CaseVector.enrichment_id,
            )
            .where(
                or_(
                    A3Case.case_id.is_(None),
                    and_(
                        CaseVector.enrichment_id.is_not(None),
                        CaseEnrichmentResult.enrichment_id.is_(None),
                    ),
                ),
            )
            .distinct()
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    async def _purge_orphan_case(self, session: AsyncSession, case_id: str) -> int:
        repo = VectorRepository(session)
        cur = await repo.get_current_vector(case_id)
        if cur is None:
            return 0

        missing_case = (
            await session.execute(select(A3Case.case_id).where(A3Case.case_id == case_id).limit(1))
        ).scalar_one_or_none() is None

        missing_enrichment = False
        if cur.enrichment_id:
            hit = await session.get(CaseEnrichmentResult, cur.enrichment_id)
            missing_enrichment = hit is None

        if not missing_case and not missing_enrichment:
            return 0

        if missing_case:
            reason = DeleteVectorIndexReason.CASE_DELETED
            cleanup_detail = "missing_a3_case"
        else:
            reason = DeleteVectorIndexReason.ENRICHMENT_DELETED
            cleanup_detail = "missing_enrichment_result"

        now = datetime.now(timezone.utc)
        job_id = uuid4().hex
        meta = {
            "delete_reason": reason.value,
            "requested_by": "system",
            "cleanup_detail": cleanup_detail,
        }
        remove_payload = VectorIndexJobCreate(
            job_id=job_id,
            case_id=case_id,
            job_type=VectorIndexJobType.REMOVE.value,
            status=EmbeddingJobStatus.SUCCEEDED.value,
            source_version=meta,
            retry_count=0,
            old_vector_id=cur.vector_id,
            old_content_hash=_case_vector_audit_hash(cur),
            started_at=now,
            finished_at=now,
        )
        deleted_vec_ids, _hist = await repo.delete_case_vector(case_id, None, remove_payload)
        await session.flush()
        return len(deleted_vec_ids)

    async def stop(self) -> None:
        """发送停止信号并取消后台任务。

        Args:
            无。

        Returns:
            ``None``。
        """
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("向量清理服务停止信号已发送")

    def start(self) -> None:
        """以 ``asyncio.create_task`` 启动周期清理。

        Args:
            无。

        Returns:
            ``None``。
        """
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_periodic())
