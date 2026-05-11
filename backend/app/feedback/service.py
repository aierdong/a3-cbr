"""反馈应用服务：提交、删除与查询编排。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_app_config
from app.feedback.exceptions import FeedbackDisabledError
from app.feedback.models import RecommendationFeedback
from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import (
    FeedbackCreateRequest,
    FeedbackDeleteRequest,
    FeedbackDeleteResponse,
    FeedbackListResponse,
    FeedbackQuery,
    FeedbackResponse,
    FeedbackStatsQuery,
    FeedbackStatsResponse,
    FeedbackTargetScope,
    FeedbackUsefulness,
    RunFeedbackResponse,
)
from app.feedback.stats import FeedbackStatsService


def feedback_row_to_response(row: RecommendationFeedback) -> FeedbackResponse:
    """ORM 行转换为对外响应。"""
    scope = (
        FeedbackTargetScope.RUN
        if row.recommendation_item_id is None
        else FeedbackTargetScope.ITEM
    )
    return FeedbackResponse(
        feedback_id=row.feedback_id,
        recommendation_run_id=row.recommendation_run_id,
        recommendation_item_id=row.recommendation_item_id,
        case_id=row.case_id,
        usefulness=FeedbackUsefulness(row.usefulness),
        comment=row.comment,
        target_scope=scope,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class FeedbackService:
    """编排字段校验结果、引用解析与持久化；不触发检索或上游写回。"""

    def __init__(
        self,
        db: AsyncSession,
        repository: FeedbackRepository,
        reference_resolver: RecommendationReferenceResolver,
    ) -> None:
        """初始化服务。

        Args:
            db: 数据库会话（统计等只读查询复用同一会话）。
            repository: 反馈仓储。
            reference_resolver: 上游推荐引用解析器。
        """
        self._db = db
        self._repo = repository
        self._resolver = reference_resolver

    async def submit_feedback(
        self,
        request: FeedbackCreateRequest,
        *,
        actor_id: str,
    ) -> FeedbackResponse:
        """校验开关后解析引用并幂等写入反馈。"""
        if not get_app_config().feedback.enabled:
            raise FeedbackDisabledError()

        normalized = request.to_normalized_input()
        ref = await self._resolver.resolve_reference(
            normalized.recommendation_run_id,
            normalized.recommendation_item_id,
        )

        row = await self._repo.upsert_feedback(
            recommendation_run_id=normalized.recommendation_run_id,
            recommendation_item_id=normalized.recommendation_item_id,
            case_id=ref.case_id,
            actor_id=actor_id,
            source_channel=normalized.source_channel.value,
            usefulness=normalized.usefulness.value,
            comment=normalized.comment,
        )

        return feedback_row_to_response(row)

    async def delete_feedback(self, request: FeedbackDeleteRequest) -> FeedbackDeleteResponse:
        """按过滤条件删除反馈，未命中时 ``deleted_count=0`` 仍为成功。"""
        deleted_count, deleted_at = await self._repo.delete_feedback(request)
        return FeedbackDeleteResponse(
            success=True,
            deleted_count=deleted_count,
            deleted_at=deleted_at,
        )

    async def list_feedback(self, query: FeedbackQuery) -> FeedbackListResponse:
        """分页过滤查询反馈明细。"""
        items = await self._repo.list_feedback(query)
        return FeedbackListResponse(items=items)

    async def get_run_feedback(self, run_id: str) -> RunFeedbackResponse:
        """单次推荐运行下全部反馈（运行级 + 推荐项级）。"""
        items = await self._repo.list_feedback(
            FeedbackQuery(recommendation_run_id=run_id, limit=500, offset=0),
        )
        return RunFeedbackResponse(recommendation_run_id=run_id, items=items)

    async def get_stats(self, query: FeedbackStatsQuery) -> FeedbackStatsResponse:
        """基础统计：数量、有用率与有用性分布。"""
        stats = FeedbackStatsService(self._db)
        return await stats.summarize(query)
