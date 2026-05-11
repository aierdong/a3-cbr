"""推荐运行和推荐项快照持久化仓储。

提供推荐运行生命周期管理（创建、完成、失败）、
推荐项快照创建和查询能力。

设计约束：
- contract_version 在 create_run 时写入，fail_run/complete_run 不得改写
- reranker_status 列 NOT NULL，数据库默认 'pending'
- recommendation_item_id 不得等于字面 'RUN'（下游哨兵保留）
- final_score=0 在降级路径或未聚合时表示占位符
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.models import (
    RecommendationItemSnapshot,
    RecommendationRun,
)
from app.retrieval.schemas import (
    AggregationStatus,
    RerankerStatus,
    RecommendationErrorData,
    RecommendationRunCreate,
    RunResult,
    RunStatus,
)


logger = logging.getLogger(__name__)

FEEDBACK_SERVICE_URL = "http://recommendation-feedback"
FEEDBACK_DELETE_TIMEOUT = 5.0


class RecommendationRepository:
    """推荐运行和推荐项快照持久化仓储。

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

    async def create_run(self, run: RecommendationRunCreate) -> RecommendationRun:
        """创建推荐运行记录。

        contract_version 在本方法中写入，创建后不得改写。

        Args:
            run: 运行创建数据。

        Returns:
            创建的运行记录 ORM 对象。
        """
        record = RecommendationRun(
            recommendation_run_id=run.recommendation_run_id,
            query_text_hash=run.query_text_hash,
            applied_filters=run.applied_filters,
            score_weights=run.score_weights,
            contract_version=run.contract_version,
            requested_top_k=run.requested_top_k,
            returned_count=0,
            vector_candidate_count=0,
            status=RunStatus.PENDING.value
            if hasattr(RunStatus, "PENDING")
            else "pending",
            reranker_model_id=run.reranker_model_id,
            reranker_status=RerankerStatus.PENDING.value,
            aggregation_status=AggregationStatus.SKIPPED.value,
            latency_ms=0,
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def complete_run(
        self,
        run_id: str,
        result: RunResult,
    ) -> RecommendationRun:
        """完成推荐运行：写入运行终态和推荐项快照。

        在同一事务内完成以下原子操作：
        1. 更新运行记录状态、候选数量、返回数量、分值聚合状态、reranker 状态、耗时
        2. 批量写入推荐项快照

        Args:
            run_id: 运行标识。
            result: 运行完成结果数据。

        Returns:
            更新后的运行记录 ORM 对象。

        Raises:
            ValueError: 运行记录不存在时抛出。
        """
        # 1. 更新运行记录
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(RecommendationRun)
            .where(RecommendationRun.recommendation_run_id == run_id)
            .values(
                status=result.status,
                returned_count=result.returned_count,
                vector_candidate_count=result.vector_candidate_count,
                reranker_status=result.reranker_status,
                aggregation_status=result.aggregation_status,
                degraded_reason=result.degraded_reason,
                latency_ms=result.latency_ms,
                updated_at=now,
            ),
        )

        # 2. 批量写入推荐项快照
        for item in result.items:
            snapshot = RecommendationItemSnapshot(
                recommendation_item_id=item.recommendation_item_id,
                recommendation_run_id=item.recommendation_run_id,
                case_id=item.case_id,
                vector_id=item.vector_id,
                rank=item.rank,
                vector_similarity_score=item.vector_similarity_score,
                semantic_similarity_score=item.semantic_similarity_score,
                structured_similarity_score=item.structured_similarity_score,
                business_score=item.business_score,
                final_score=item.final_score,
                score_breakdown=item.score_breakdown,
                explanation_status=item.explanation_status.value
                if hasattr(item.explanation_status, "value")
                else item.explanation_status,
                missing_fields=item.missing_fields,
                case_updated_at=item.case_updated_at,
            )
            self._db.add(snapshot)

        await self._db.flush()

        # 返回更新后的运行记录
        run_record = await self.get_run(run_id)
        if run_record is None:
            raise ValueError(f"运行记录不存在: {run_id}")
        return run_record

    async def fail_run(
        self,
        run_id: str,
        error: RecommendationErrorData,
    ) -> RecommendationRun:
        """标记推荐运行失败。

        contract_version 不得在本方法中改写。

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
            update(RecommendationRun)
            .where(RecommendationRun.recommendation_run_id == run_id)
            .values(
                status=RunStatus.FAILED,
                error_code=error.error_code,
                updated_at=now,
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

    async def get_run(self, run_id: str) -> Optional[RecommendationRun]:
        """按 run_id 查询运行记录。

        Args:
            run_id: 运行标识。

        Returns:
            运行记录 ORM 对象，不存在时返回 None。
        """
        stmt = select(RecommendationRun).where(
            RecommendationRun.recommendation_run_id == run_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_run_with_items(
        self, run_id: str
    ) -> tuple[Optional[RecommendationRun], list[RecommendationItemSnapshot]]:
        """按 run_id 查询运行记录及其推荐项快照。

        Args:
            run_id: 运行标识。

        Returns:
            (运行记录, 推荐项快照列表)，不存在时返回 (None, [])。
        """
        run = await self.get_run(run_id)
        if run is None:
            return None, []

        stmt = select(RecommendationItemSnapshot).where(
            RecommendationItemSnapshot.recommendation_run_id == run_id,
        ).order_by(RecommendationItemSnapshot.rank)
        result = await self._db.execute(stmt)
        items = list(result.scalars().all())

        return run, items

    async def get_items_by_run(
        self, run_id: str
    ) -> list[RecommendationItemSnapshot]:
        """按 run_id 查询推荐项快照列表。

        Args:
            run_id: 运行标识。

        Returns:
            推荐项快照列表。
        """
        stmt = select(RecommendationItemSnapshot).where(
            RecommendationItemSnapshot.recommendation_run_id == run_id,
        ).order_by(RecommendationItemSnapshot.rank)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_item_by_id(
        self, item_id: str
    ) -> Optional[RecommendationItemSnapshot]:
        """按 item_id 查询推荐项快照。

        Args:
            item_id: 推荐项标识。

        Returns:
            推荐项快照 ORM 对象，不存在时返回 None。
        """
        stmt = select(RecommendationItemSnapshot).where(
            RecommendationItemSnapshot.recommendation_item_id == item_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # 删除操作（级联删除由 service 层编排）
    # ------------------------------------------------------------------

    async def delete_run(self, run_id: str) -> bool:
        """删除推荐运行记录。

        Args:
            run_id: 运行标识。

        Returns:
            是否成功删除。
        """
        del_result = await self._db.execute(
            delete(RecommendationRun).where(
                RecommendationRun.recommendation_run_id == run_id,
            ),
        )
        await self._db.flush()
        return del_result.rowcount > 0

    async def delete_items_by_run(self, run_id: str) -> int:
        """删除指定运行的所有推荐项快照。

        Args:
            run_id: 运行标识。

        Returns:
            删除的记录数。
        """
        del_result = await self._db.execute(
            delete(RecommendationItemSnapshot).where(
                RecommendationItemSnapshot.recommendation_run_id == run_id,
            ),
        )
        await self._db.flush()
        return del_result.rowcount

    async def delete_items(self, item_ids: list[str]) -> int:
        """删除指定标识的推荐项快照。

        Args:
            item_ids: 推荐项标识列表。

        Returns:
            删除的记录数。
        """
        del_result = await self._db.execute(
            delete(RecommendationItemSnapshot).where(
                RecommendationItemSnapshot.recommendation_item_id.in_(item_ids),
            ),
        )
        await self._db.flush()
        return del_result.rowcount


# =============================================================================
# 级联删除编排（调用 recommendation-feedback 删除接口）
# =============================================================================


class RecommendationCascadeDeleteService:
    """推荐运行级联删除服务。

    负责删除推荐运行/推荐项快照时同步清理关联的反馈记录。

    设计约束：
    - 反馈删除失败不阻塞推荐记录删除，但须记录告警日志
    - 推荐项删除顺序：先调反馈删除 → 再删快照
    - 运行删除顺序：先删快照 → 调反馈删除 → 删运行
    """

    def __init__(
        self,
        repository: "RecommendationRepository",
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """初始化级联删除服务。

        Args:
            repository: 推荐仓储实例
            http_client: 可选的 HTTP 客户端（用于测试注入）
        """
        self._repo = repository
        self._http_client = http_client

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=FEEDBACK_DELETE_TIMEOUT)

    async def delete_recommendation_run(
        self, run_id: str
    ) -> tuple[int, int, int]:
        """删除推荐运行及其关联的推荐项快照和反馈记录。

        执行顺序：
        1. 删除推荐项快照
        2. 调用反馈规格删除接口清理关联反馈
        3. 删除推荐运行记录

        Args:
            run_id: 运行标识

        Returns:
            tuple[快照删除数, 反馈删除数, 运行删除数]
        """
        items_deleted = await self._repo.delete_items_by_run(run_id)

        feedback_deleted_count = await self._call_feedback_delete_by_run(run_id)

        run_deleted = await self._repo.delete_run(run_id)
        run_deleted_count = 1 if run_deleted else 0

        return items_deleted, feedback_deleted_count, run_deleted_count

    async def delete_recommendation_items(
        self, item_ids: list[str]
    ) -> tuple[int, int]:
        """删除推荐项快照及其关联反馈记录。

        执行顺序：
        1. 调用反馈规格删除接口清理关联反馈
        2. 删除推荐项快照

        Args:
            item_ids: 推荐项标识列表

        Returns:
            tuple[反馈删除数, 快照删除数]
        """
        feedback_deleted_count = await self._call_feedback_delete_by_items(
            item_ids
        )

        items_deleted = await self._repo.delete_items(item_ids)

        return feedback_deleted_count, items_deleted

    async def _call_feedback_delete_by_run(
        self, run_id: str
    ) -> int:
        """调用反馈删除接口清理运行级关联反馈。

        Args:
            run_id: 推荐运行标识

        Returns:
            删除的反馈记录数
        """
        try:
            client = await self._get_http_client()
            response = await client.delete(
                f"{FEEDBACK_SERVICE_URL}/api/recommendation-feedback",
                params={"recommendation_run_id": run_id},
                timeout=FEEDBACK_DELETE_TIMEOUT,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("deleted_count", 0)
            elif response.status_code == 404:
                return 0
            else:
                logger.warning(
                    f"Feedback delete by run failed: {response.status_code}",
                    extra={"run_id": run_id},
                )
                return 0
        except httpx.TimeoutException:
            logger.warning(
                "Feedback service timeout during run cascade delete",
                extra={"run_id": run_id},
            )
            return 0
        except httpx.ConnectError as e:
            logger.warning(
                f"Cannot connect to feedback service during run cascade delete: {e}",
                extra={"run_id": run_id},
            )
            return 0
        except Exception as e:
            logger.warning(
                f"Unexpected error during feedback delete by run: {e}",
                extra={"run_id": run_id},
            )
            return 0

    async def _call_feedback_delete_by_items(
        self, item_ids: list[str]
    ) -> int:
        """调用反馈删除接口按推荐项批量删除反馈。

        Args:
            item_ids: 推荐项标识列表

        Returns:
            删除的反馈记录数
        """
        total_deleted = 0
        for item_id in item_ids:
            try:
                client = await self._get_http_client()
                response = await client.delete(
                    f"{FEEDBACK_SERVICE_URL}/api/recommendation-feedback",
                    params={"recommendation_item_id": item_id},
                    timeout=FEEDBACK_DELETE_TIMEOUT,
                )
                if response.status_code == 200:
                    data = response.json()
                    total_deleted += data.get("deleted_count", 0)
                elif response.status_code == 404:
                    pass
                else:
                    logger.warning(
                        f"Feedback delete by item failed: {response.status_code}",
                        extra={"item_id": item_id},
                    )
            except httpx.TimeoutException:
                logger.warning(
                    "Feedback service timeout during item cascade delete",
                    extra={"item_id": item_id},
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Cannot connect to feedback service during item cascade delete: {e}",
                    extra={"item_id": item_id},
                )
            except Exception as e:
                logger.warning(
                    f"Unexpected error during feedback delete by item: {e}",
                    extra={"item_id": item_id},
                )
        return total_deleted