"""推荐反馈 ORM 模型。

表 `recommendation_feedback`：`recommendation_item_id` 为 NULL 表示运行级反馈；
非 NULL 表示推荐项级反馈。同一 `(actor_id, recommendation_run_id, recommendation_item_id)`
在 PostgreSQL 15+ 下通过 `UNIQUE NULLS NOT DISTINCT` 保证幂等。
"""

from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint, func

from app.db.base import Base


class RecommendationFeedback(Base):
    """推荐反馈记录。"""

    __tablename__ = "recommendation_feedback"

    feedback_id = Column(String(64), primary_key=True)
    recommendation_run_id = Column(String(64), nullable=False)
    recommendation_item_id = Column(String(64), nullable=True)
    case_id = Column(String(64), nullable=True)
    actor_id = Column(String(64), nullable=False)
    source_channel = Column(String(32), nullable=False)
    usefulness = Column(String(32), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "recommendation_run_id",
            "recommendation_item_id",
            name="unique_feedback_target",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_recommendation_feedback_run_id", "recommendation_run_id"),
        Index("ix_recommendation_feedback_item_id", "recommendation_item_id"),
        Index("ix_recommendation_feedback_case_id", "case_id"),
        Index("ix_recommendation_feedback_actor_id", "actor_id"),
        Index("ix_recommendation_feedback_created_at", "created_at"),
        Index("ix_recommendation_feedback_usefulness", "usefulness"),
    )
