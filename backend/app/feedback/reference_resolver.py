"""推荐运行与推荐项引用解析（存在性与一致性校验）。"""

from dataclasses import dataclass

from app.feedback.exceptions import FeedbackTargetMismatchError, FeedbackTargetNotFoundError
from app.retrieval.repository import RecommendationRepository


@dataclass(frozen=True, slots=True)
class RecommendationReference:
    """上游推荐引用解析结果（只读标识与关联 ``case_id``）。"""

    recommendation_run_id: str
    recommendation_item_id: str | None
    case_id: str | None


class RecommendationReferenceResolver:
    """解析 `recommendation_run_id` 与可选 `recommendation_item_id`，返回关联数据。

    仅通过 `RecommendationRepository` 只读查询上游表，不触发检索、重排或写回。
    """

    def __init__(self, repository: RecommendationRepository) -> None:
        """初始化解析器。

        Args:
            repository: 推荐运行 / 推荐项快照仓储。
        """
        self._repo = repository

    async def resolve_reference(
        self,
        run_id: str,
        item_id: str | None,
    ) -> RecommendationReference:
        """校验运行（及可选推荐项）存在且一致，返回 `RecommendationReference`。

        Args:
            run_id: 推荐运行标识。
            item_id: 推荐项标识；``None`` 表示运行级反馈目标。

        Returns:
            包含 ``case_id``（仅推荐项级为非空）的引用对象。

        Raises:
            FeedbackTargetNotFoundError: 运行不存在，或推荐项快照不存在。
            FeedbackTargetMismatchError: 推荐项不属于该运行。
        """
        run = await self._repo.get_run(run_id)
        if run is None:
            raise FeedbackTargetNotFoundError()

        if item_id is None:
            return RecommendationReference(
                recommendation_run_id=run_id,
                recommendation_item_id=None,
                case_id=None,
            )

        snapshot = await self._repo.get_item_by_id(item_id)
        if snapshot is None:
            raise FeedbackTargetNotFoundError()
        if snapshot.recommendation_run_id != run_id:
            raise FeedbackTargetMismatchError()

        return RecommendationReference(
            recommendation_run_id=run_id,
            recommendation_item_id=item_id,
            case_id=snapshot.case_id,
        )
