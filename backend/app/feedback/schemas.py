"""推荐反馈 Pydantic 契约（提交、删除、查询、统计与清理触发）。"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import get_app_config


class FeedbackSourceChannel(StrEnum):
    """反馈来源渠道。"""

    ADMIN_WEB = "admin_web"
    API = "api"
    SYSTEM = "system"


class FeedbackUsefulness(StrEnum):
    """有用性枚举。"""

    USEFUL = "useful"
    NOT_USEFUL = "not_useful"
    UNKNOWN = "unknown"


class FeedbackTargetScope(StrEnum):
    """反馈目标级别：整体推荐运行级或单条推荐项级。"""

    RUN = "run"
    ITEM = "item"


class FeedbackDeleteReason(StrEnum):
    """删除原因（审计）。"""

    CASE_DELETED = "case_deleted"
    ENRICHMENT_DELETED = "enrichment_deleted"
    VECTOR_DELETED = "vector_deleted"
    FEEDBACK_DELETED = "feedback_deleted"
    SCHEDULE_DELETED = "schedule_deleted"


class FeedbackDeleteRequestedBy(StrEnum):
    """删除者标识。"""

    ANONYMOUS_USER = "anonymous_user"
    SYSTEM = "system"


class FeedbackCreateRequest(BaseModel):
    """反馈提交请求。"""

    model_config = ConfigDict(extra="forbid")

    recommendation_run_id: str = Field(..., max_length=64)
    recommendation_item_id: str | None = Field(None, max_length=64)
    usefulness: FeedbackUsefulness
    comment: str | None = None
    source_channel: FeedbackSourceChannel = Field(
        default=FeedbackSourceChannel.ADMIN_WEB,
    )

    @field_validator("comment")
    @classmethod
    def validate_comment_length(cls, value: str | None) -> str | None:
        """校验备注长度不超过配置上限。

        Args:
            value: 原始备注。

        Returns:
            通过校验的备注或 None。

        Raises:
            ValueError: 超出最大长度。
        """
        if value is None:
            return value
        max_len = get_app_config().feedback.comment_max_length
        if len(value) > max_len:
            msg = f"comment exceeds max length {max_len}"
            raise ValueError(msg)
        return value


class FeedbackDeleteRequest(BaseModel):
    """反馈删除请求。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str | None = Field(None, max_length=64)
    feedback_id: str | None = Field(None, max_length=64)
    recommendation_run_id: str | None = Field(None, max_length=64)
    recommendation_item_id: str | None = Field(None, max_length=64)
    reason: FeedbackDeleteReason
    requested_by: FeedbackDeleteRequestedBy

    @model_validator(mode="after")
    def at_least_one_target_filter(self) -> "FeedbackDeleteRequest":
        """至少提供一个删除过滤条件。

        Args:
            self: 当前请求实例。

        Returns:
            FeedbackDeleteRequest: 校验后的请求。

        Raises:
            ValueError: 未提供任何过滤字段。
        """
        if not any(
            [
                self.case_id,
                self.feedback_id,
                self.recommendation_run_id,
                self.recommendation_item_id,
            ]
        ):
            raise ValueError(
                "at least one of case_id, feedback_id, "
                "recommendation_run_id, recommendation_item_id is required"
            )
        return self


class CleanupTriggerRequest(BaseModel):
    """手动触发反馈清理请求（管理端）。"""

    model_config = ConfigDict(extra="forbid")

    reason: FeedbackDeleteReason
    requested_by: FeedbackDeleteRequestedBy

    @model_validator(mode="after")
    def fixed_cleanup_actor(self) -> "CleanupTriggerRequest":
        """约束为定时清理语义（运维手动触发）。

        Args:
            self: 当前请求实例。

        Returns:
            CleanupTriggerRequest: 校验后的请求。

        Raises:
            ValueError: 枚举不符合固定约束。
        """
        if self.reason != FeedbackDeleteReason.SCHEDULE_DELETED:
            raise ValueError("reason must be schedule_deleted")
        if self.requested_by != FeedbackDeleteRequestedBy.SYSTEM:
            raise ValueError("requested_by must be system")
        return self


class FeedbackQuery(BaseModel):
    """反馈明细过滤查询参数。"""

    model_config = ConfigDict(extra="forbid")

    recommendation_run_id: str | None = Field(None, max_length=64)
    recommendation_item_id: str | None = Field(None, max_length=64)
    case_id: str | None = Field(None, max_length=64)
    actor_id: str | None = Field(None, max_length=64)
    usefulness: FeedbackUsefulness | None = None
    created_at_from: datetime | None = None
    created_at_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class FeedbackStatsGroupBy(StrEnum):
    """统计聚合维度。"""

    NONE = "none"
    RECOMMENDATION_RUN = "recommendation_run"
    CASE = "case"


class FeedbackStatsQuery(BaseModel):
    """基础统计查询参数。"""

    model_config = ConfigDict(extra="forbid")

    recommendation_run_id: str | None = Field(None, max_length=64)
    case_id: str | None = Field(None, max_length=64)
    created_at_from: datetime | None = None
    created_at_to: datetime | None = None
    group_by: FeedbackStatsGroupBy = Field(default=FeedbackStatsGroupBy.NONE)


class QueryContextSummary(BaseModel):
    """来自 recommendation_runs 的查询上下文字段（关联查询填充）。"""

    model_config = ConfigDict(extra="forbid")

    query_hash: str = Field(..., max_length=128)
    applied_filters_summary: str = Field(
        ...,
        description="过滤条件摘要（脱敏或截断，非完整 JSON 镜像）",
    )
    vector_candidate_count: int = Field(..., ge=0)
    returned_count: int = Field(..., ge=0)


class ItemRecommendationDetail(BaseModel):
    """来自 recommendation_item_snapshots 的推荐项明细（关联查询填充）。"""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(..., ge=0)
    vector_similarity_score: float
    semantic_similarity_score: float | None = None
    structured_similarity_score: float | None = None
    business_score: float | None = None
    final_score: float
    explanation_status: str = Field(..., max_length=32)


class FeedbackResponse(BaseModel):
    """单条反馈核心响应字段。"""

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(..., max_length=64)
    recommendation_run_id: str = Field(..., max_length=64)
    recommendation_item_id: str | None = Field(None, max_length=64)
    case_id: str | None = Field(None, max_length=64)
    usefulness: FeedbackUsefulness
    comment: str | None = None
    target_scope: FeedbackTargetScope
    created_at: datetime
    updated_at: datetime


class FeedbackListItem(FeedbackResponse):
    """明细列表项：核心字段 + 提交者与来源。"""

    actor_id: str = Field(..., max_length=64)
    source_channel: FeedbackSourceChannel
    query_context: QueryContextSummary | None = None
    item_detail: ItemRecommendationDetail | None = None


class FeedbackListResponse(BaseModel):
    """反馈明细分页响应。"""

    model_config = ConfigDict(extra="forbid")

    items: list[FeedbackListItem] = Field(default_factory=list)


class RunFeedbackResponse(BaseModel):
    """单次推荐运行下全部反馈（含运行级与推荐项级）。"""

    model_config = ConfigDict(extra="forbid")

    recommendation_run_id: str = Field(..., max_length=64)
    items: list[FeedbackListItem] = Field(default_factory=list)


class FeedbackStatsGroupRow(BaseModel):
    """统计口径下单行聚合结果。"""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["none", "recommendation_run", "case"] = "none"
    recommendation_run_id: str | None = Field(None, max_length=64)
    case_id: str | None = Field(None, max_length=64)
    total_count: int = Field(default=0, ge=0)
    useful_count: int = Field(default=0, ge=0)
    not_useful_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    useful_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    not_useful_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    unknown_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class FeedbackStatsResponse(BaseModel):
    """基础统计响应：总体与可选分组。"""

    model_config = ConfigDict(extra="forbid")

    overall: FeedbackStatsGroupRow
    groups: list[FeedbackStatsGroupRow] = Field(default_factory=list)


class FeedbackDeleteResponse(BaseModel):
    """反馈删除响应。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    deleted_count: int = Field(..., ge=0)
    deleted_at: datetime


class CleanupResult(BaseModel):
    """清理任务执行结果。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    scanned_count: int = Field(..., ge=0)
    deleted_count: int = Field(..., ge=0)
    duration_ms: int = Field(..., ge=0)
