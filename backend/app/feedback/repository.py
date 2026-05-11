"""反馈聚合根持久化（幂等 upsert、删除与查询）。"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.feedback.models import RecommendationFeedback


class FeedbackRepository:
    """反馈表数据访问：依赖 AsyncSession，事务由调用方提交。"""

    def __init__(self, db: AsyncSession) -> None:
        """初始化仓储。

        Args:
            db: 异步数据库会话。
        """
        self._db = db

    async def _get_by_natural_key(
        self,
        *,
        actor_id: str,
        recommendation_run_id: str,
        recommendation_item_id: str | None,
    ) -> RecommendationFeedback | None:
        stmt = select(RecommendationFeedback).where(
            RecommendationFeedback.actor_id == actor_id,
            RecommendationFeedback.recommendation_run_id == recommendation_run_id,
        )
        if recommendation_item_id is None:
            stmt = stmt.where(RecommendationFeedback.recommendation_item_id.is_(None))
        else:
            stmt = stmt.where(
                RecommendationFeedback.recommendation_item_id == recommendation_item_id,
            )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_feedback(
        self,
        *,
        recommendation_run_id: str,
        recommendation_item_id: str | None,
        case_id: str | None,
        actor_id: str,
        source_channel: str,
        usefulness: str,
        comment: str | None,
    ) -> RecommendationFeedback:
        """按 `(actor_id, recommendation_run_id, recommendation_item_id)` 幂等写入。

        不存在则插入；存在则更新有用性、备注、来源渠道、`case_id` 与 `updated_at`。

        Args:
            recommendation_run_id: 推荐运行标识。
            recommendation_item_id: 推荐项标识，运行级反馈为 ``None``。
            case_id: 命中案例标识；运行级为 ``None``。
            actor_id: 提交者标识。
            source_channel: 来源渠道枚举值字符串。
            usefulness: 有用性枚举值字符串。
            comment: 备注正文，可为 ``None``。

        Returns:
            写入后的 ORM 实体。
        """
        feedback_id = secrets.token_hex(24)

        stmt = insert(RecommendationFeedback).values(
            feedback_id=feedback_id,
            recommendation_run_id=recommendation_run_id,
            recommendation_item_id=recommendation_item_id,
            case_id=case_id,
            actor_id=actor_id,
            source_channel=source_channel,
            usefulness=usefulness,
            comment=comment,
        )
        excluded = stmt.excluded
        now = datetime.now(timezone.utc)
        stmt = stmt.on_conflict_do_update(
            constraint="unique_feedback_target",
            set_={
                "usefulness": excluded.usefulness,
                "comment": excluded.comment,
                "source_channel": excluded.source_channel,
                "case_id": excluded.case_id,
                "updated_at": now,
            },
        )

        await self._db.execute(stmt)
        await self._db.flush()
        # INSERT .. ON CONFLICT 更新后，同会话内已有实例可能未刷新，强制过期后再读。
        self._db.expire_all()

        row = await self._get_by_natural_key(
            actor_id=actor_id,
            recommendation_run_id=recommendation_run_id,
            recommendation_item_id=recommendation_item_id,
        )
        if row is None:
            msg = "feedback upsert failed to load row after insert/update"
            raise RuntimeError(msg)
        return row
