"""反馈应用服务：提交、删除与查询编排。"""

from app.core.config import get_app_config
from app.feedback.exceptions import FeedbackDisabledError
from app.feedback.models import RecommendationFeedback
from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import (
    FeedbackCreateRequest,
    FeedbackDeleteRequest,
    FeedbackDeleteResponse,
    FeedbackResponse,
    FeedbackTargetScope,
    FeedbackUsefulness,
)


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
        repository: FeedbackRepository,
        reference_resolver: RecommendationReferenceResolver,
    ) -> None:
        """初始化服务。

        Args:
            repository: 反馈仓储。
            reference_resolver: 上游推荐引用解析器。
        """
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
