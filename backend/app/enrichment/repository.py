"""案例增强派生结果与运行记录持久化仓储。

提供增强运行生命周期管理（创建、成功、失败）、
派生结果查询和删除能力。
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.models import (
    CaseEnrichmentResult,
    CaseEnrichmentRun,
    RecommendationCopyRun,
)
from app.enrichment.schemas import (
    CaseEnrichmentResultCreate,
    DeleteEnrichmentResult,
    EnrichmentErrorData,
    EnrichmentRunCreate,
    EnrichmentStatus,
    RecommendationCopyRunCreate,
    RunStatus,
)


class EnrichmentRepository:
    """案例增强派生结果与运行记录持久化仓储。

    所有写操作通过传入的 AsyncSession 进行，
    事务提交由调用方（如 get_db 依赖）负责。
    """

    def __init__(self, db: AsyncSession) -> None:
        """初始化仓储。

        Args:
            db: 异步数据库会话。
        """
        self._db = db

    # ------------------------------------------------------------------
    # 运行记录操作
    # ------------------------------------------------------------------

    async def create_run(self, run: EnrichmentRunCreate) -> CaseEnrichmentRun:
        """创建增强运行记录。

        Args:
            run: 运行创建数据。

        Returns:
            创建的运行记录 ORM 对象。
        """
        record = CaseEnrichmentRun(
            run_id=run.run_id,
            case_id=run.case_id,
            task_type=run.task_type,
            status=run.status,
            model_id=run.model_id,
            request_purpose=run.request_purpose,
            case_updated_at=run.case_updated_at,
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def complete_run(
        self,
        run_id: str,
        result: CaseEnrichmentResultCreate,
    ) -> CaseEnrichmentRun:
        """完成增强运行：写入新 valid 结果并更新运行状态。

        在同一事务内完成以下原子操作：
        1. 删除该 case_id 的旧派生结果
        2. 写入新的 valid 派生结果
        3. 更新运行记录状态为 succeeded

        Args:
            run_id: 运行标识。
            result: 派生结果创建数据。

        Returns:
            更新后的运行记录 ORM 对象。

        Raises:
            ValueError: 运行记录不存在时抛出。
        """
        # 1. 删除该 case_id 的旧派生结果
        await self._db.execute(
            delete(CaseEnrichmentResult).where(
                CaseEnrichmentResult.case_id == result.case_id,
            ),
        )

        # 2. 写入新的 valid 派生结果
        new_result = CaseEnrichmentResult(
            enrichment_id=result.enrichment_id,
            case_id=result.case_id,
            case_updated_at=result.case_updated_at,
            status=result.status,
            problem_summary=result.problem_summary,
            solution_summary=result.solution_summary,
            structured_suggestions=result.structured_suggestions,
            tag_suggestions=result.tag_suggestions,
            source_references=result.source_references,
            output_version=result.output_version,
        )
        self._db.add(new_result)

        # 3. 更新运行记录状态为 succeeded
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(CaseEnrichmentRun)
            .where(CaseEnrichmentRun.run_id == run_id)
            .values(
                status=RunStatus.SUCCEEDED,
                finished_at=now,
            ),
        )

        await self._db.flush()

        # 返回更新后的运行记录
        run_record = await self.get_run(run_id)
        if run_record is None:
            raise ValueError(f"运行记录不存在: {run_id}")
        return run_record

    async def fail_run(
        self,
        run_id: str,
        error: EnrichmentErrorData,
    ) -> CaseEnrichmentRun:
        """标记增强运行失败。

        Args:
            run_id: 运行标识。
            error: 错误数据。

        Returns:
            更新后的运行记录 ORM 对象。

        Raises:
            ValueError: 运行记录不存在时抛出。
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(CaseEnrichmentRun)
            .where(CaseEnrichmentRun.run_id == run_id)
            .values(
                status=RunStatus.FAILED,
                error_code=error.error_code,
                error_stage=error.error_stage,
                finished_at=now,
            ),
        )
        await self._db.flush()

        run_record = await self.get_run(run_id)
        if run_record is None:
            raise ValueError(f"运行记录不存在: {run_id}")
        return run_record

    async def mark_retryable(
        self,
        run_id: str,
        error: EnrichmentErrorData,
    ) -> CaseEnrichmentRun:
        """标记增强运行为可重试。

        用于供应商或临时失败（如超时、限流），允许用户通过
        retry_run 创建新的运行记录重新执行。

        Args:
            run_id: 运行标识。
            error: 错误数据。

        Returns:
            更新后的运行记录 ORM 对象。

        Raises:
            ValueError: 运行记录不存在时抛出。
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(CaseEnrichmentRun)
            .where(CaseEnrichmentRun.run_id == run_id)
            .values(
                status=RunStatus.RETRYABLE,
                error_code=error.error_code,
                error_stage=error.error_stage,
                finished_at=now,
            ),
        )
        await self._db.flush()

        run_record = await self.get_run(run_id)
        if run_record is None:
            raise ValueError(f"运行记录不存在: {run_id}")
        return run_record

    # ------------------------------------------------------------------
    # 查询操作
    # ------------------------------------------------------------------

    async def get_current_result(
        self,
        case_id: str,
    ) -> Optional[CaseEnrichmentResult]:
        """查询当前有效的派生结果。

        按 case_id 查询 status=valid 的派生结果。

        Args:
            case_id: 案例标识。

        Returns:
            有效的派生结果 ORM 对象，不存在时返回 None。
        """
        stmt = select(CaseEnrichmentResult).where(
            CaseEnrichmentResult.case_id == case_id,
            CaseEnrichmentResult.status == EnrichmentStatus.VALID,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_run(self, run_id: str) -> Optional[CaseEnrichmentRun]:
        """按 run_id 查询运行记录。

        Args:
            run_id: 运行标识。

        Returns:
            运行记录 ORM 对象，不存在时返回 None。
        """
        stmt = select(CaseEnrichmentRun).where(
            CaseEnrichmentRun.run_id == run_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # 删除操作
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 推荐文案运行记录操作
    # ------------------------------------------------------------------

    async def create_recommendation_copy_run(
        self,
        run: RecommendationCopyRunCreate,
    ) -> RecommendationCopyRun:
        """创建推荐文案运行记录。

        Args:
            run: 推荐文案运行创建数据。

        Returns:
            创建的推荐文案运行记录 ORM 对象。
        """
        record = RecommendationCopyRun(
            copy_run_id=run.copy_run_id,
            query_text_hash=run.query_text_hash,
            status=run.status,
            candidate_case_ids=run.candidate_case_ids,
            items=run.items,
            model_id=run.model_id,
            request_purpose=run.request_purpose,
            token_usage=run.token_usage,
            schema_validation_status=run.schema_validation_status,
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def delete_enrichment_data(
        self,
        case_id: Optional[str] = None,
        enrichment_id: Optional[str] = None,
    ) -> DeleteEnrichmentResult:
        """删除案例的所有派生结果和运行记录。

        在同一事务内完成以下原子操作：
        1. 删除匹配的派生结果
        2. 删除匹配的运行记录

        支持幂等删除：不存在时返回 deleted_count=0。

        Args:
            case_id: 案例标识，按案例删除所有增强数据。
            enrichment_id: 增强标识，删除特定增强记录。

        Returns:
            删除结果。

        Raises:
            ValueError: 未提供 case_id 或 enrichment_id 时抛出。
        """
        if case_id is None and enrichment_id is None:
            raise ValueError(
                "至少提供 case_id 或 enrichment_id 之一",
            )

        deleted_count = 0
        target_case_id = case_id

        if enrichment_id is not None:
            # 先查询 enrichment_id 对应的 case_id（用于后续删除运行记录）
            stmt = select(CaseEnrichmentResult.case_id).where(
                CaseEnrichmentResult.enrichment_id == enrichment_id,
            )
            result = await self._db.execute(stmt)
            target_case_id = result.scalar_one_or_none()

            # 删除该 enrichment_id 的派生结果
            if target_case_id is not None:
                del_result = await self._db.execute(
                    delete(CaseEnrichmentResult).where(
                        CaseEnrichmentResult.enrichment_id == enrichment_id,
                    ),
                )
                deleted_count += del_result.rowcount

        if target_case_id is not None:
            # 删除该 case_id 的所有派生结果（如果按 case_id 删除）
            if case_id is not None:
                del_result = await self._db.execute(
                    delete(CaseEnrichmentResult).where(
                        CaseEnrichmentResult.case_id == target_case_id,
                    ),
                )
                deleted_count += del_result.rowcount

            # 删除该 case_id 的所有运行记录
            del_result = await self._db.execute(
                delete(CaseEnrichmentRun).where(
                    CaseEnrichmentRun.case_id == target_case_id,
                ),
            )
            deleted_count += del_result.rowcount

        await self._db.flush()

        return DeleteEnrichmentResult(
            success=True,
            deleted_count=deleted_count,
            deleted_at=datetime.now(timezone.utc),
        )
