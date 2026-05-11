"""推荐运行和推荐项快照 ORM 模型。

定义 recommendation_runs 和 recommendation_item_snapshots 两张表：
- recommendation_runs: 推荐运行记录，含 contract_version、reranker_status 等
- recommendation_item_snapshots: 推荐项快照，含分值明细和解释状态

设计约束：
- contract_version 在 create_run 时写入，fail_run/complete_run 不得改写
- reranker_status 列 NOT NULL，数据库默认 'pending'
- recommendation_item_id 不得等于字面 'RUN'（下游 recommendation-feedback 哨兵）
"""

from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class RunStatus(str, Enum):
    """推荐运行状态枚举。"""

    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    DEGRADED = "degraded"
    FAILED = "failed"


class RerankerStatus(str, Enum):
    """Reranker 状态枚举。

    - pending（默认）：尚未得到重排外呼的最终结果，含从未进入重排阶段的终态路径
    - succeeded：重排外呼成功并完成分值写入
    - failed：已发起重排外呼且失败
    - skipped：明确选择不调用远程 reranker
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AggregationStatus(str, Enum):
    """分值聚合状态枚举。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExplanationStatus(str, Enum):
    """推荐解释状态枚举。"""

    GENERATED = "generated"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"


class RecommendationRun(Base):
    """推荐运行记录表。

    记录每次相似案例检索的生命周期：运行状态、查询哈希、过滤条件、
    业务权重、候选数量、分值聚合状态、reranker 状态和耗时。
    """

    __tablename__ = "recommendation_runs"

    recommendation_run_id = Column(String(64), primary_key=True)
    query_text_hash = Column(String(128), nullable=False)
    applied_filters = Column(JSONB, nullable=False)
    score_weights = Column(JSONB, nullable=False)
    contract_version = Column(String(64), nullable=False)
    requested_top_k = Column(Integer, nullable=False)
    returned_count = Column(Integer, nullable=False)
    vector_candidate_count = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, index=True)
    degraded_reason = Column(String(128), nullable=True)
    reranker_model_id = Column(String(128), nullable=False)
    reranker_status = Column(
        String(32), nullable=False, default=RerankerStatus.PENDING.value
    )
    aggregation_status = Column(String(32), nullable=False)
    latency_ms = Column(Integer, nullable=False)
    error_code = Column(String(64), nullable=True)
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
        Index("ix_recommendation_runs_created_at", "created_at"),
        Index("ix_recommendation_runs_status", "status"),
        Index("ix_recommendation_runs_query_text_hash", "query_text_hash"),
    )


class RecommendationItemSnapshot(Base):
    """推荐项快照表。

    保存每个推荐项的分值明细、排序位置、解释状态和缺失字段。
    不保存完整问题原文、完整案例正文、向量数组或反馈结果。
    """

    __tablename__ = "recommendation_item_snapshots"

    recommendation_item_id = Column(String(64), primary_key=True)
    recommendation_run_id = Column(String(64), nullable=False, index=True)
    case_id = Column(String(64), nullable=False)
    vector_id = Column(String(64), nullable=False)
    rank = Column(Integer, nullable=False)
    vector_similarity_score = Column(Float, nullable=False)
    semantic_similarity_score = Column(Float, nullable=True)
    structured_similarity_score = Column(Float, nullable=True)
    business_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=False, default=0.0)
    score_breakdown = Column(JSONB, nullable=False)
    explanation_status = Column(String(32), nullable=False)
    missing_fields = Column(JSONB, nullable=False)
    case_updated_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_recommendation_item_snapshots_case_id", "case_id"),
        Index(
            "ix_recommendation_item_snapshots_run_rank",
            "recommendation_run_id",
            "rank",
        ),
    )