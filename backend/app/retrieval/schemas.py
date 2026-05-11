"""推荐运行和推荐项快照 Pydantic Schema。

定义检索推荐内部服务和仓储层之间的契约，以及 API 响应契约：
- RecommendationRunCreate / RecommendationItemCreate: 内部创建 Schema
- RecommendationRunRecord / RecommendationItemRecord: 内部记录 Schema
- RecommendationRunResponse / RecommendationItemResponse: API 响应 Schema

设计约束：
- recommendation_item_id 不得等于字面 'RUN'（下游 recommendation-feedback 哨兵保留）
- final_score=0 在 score_breakdown.final_score_source='default_zero_not_aggregated' 时表示未聚合
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# 枚举定义
# =============================================================================


class RunStatus(StrEnum):
    """推荐运行状态枚举。"""

    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    DEGRADED = "degraded"
    FAILED = "failed"


class RerankerStatus(StrEnum):
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


class AggregationStatus(StrEnum):
    """分值聚合状态枚举。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExplanationStatus(StrEnum):
    """推荐解释状态枚举。"""

    GENERATED = "generated"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"


class ScoreBreakdownSource(StrEnum):
    """最终分值来源枚举。

    - aggregated: 成功聚合后的分值
    - default_zero_not_aggregated: 未聚合或降级路径的占位符
    """

    AGGREGATED = "aggregated"
    DEFAULT_ZERO_NOT_AGGREGATED = "default_zero_not_aggregated"


# =============================================================================
# 内部创建 Schema（服务层 → 仓储层）
# =============================================================================


class RecommendationRunCreate(BaseModel):
    """创建推荐运行记录的内部 Schema。"""

    recommendation_run_id: str = Field(..., max_length=64, description="推荐运行标识")
    query_text_hash: str = Field(..., max_length=128, description="查询文本哈希")
    applied_filters: dict[str, Any] = Field(..., description="规范化过滤条件")
    score_weights: dict[str, float] = Field(..., description="聚合权重配置")
    contract_version: str = Field(..., max_length=64, description="依赖契约版本标识")
    requested_top_k: int = Field(..., ge=1, description="请求 Top-K")
    reranker_model_id: str = Field(..., max_length=128, description="重排模型标识")

    model_config = ConfigDict(extra="forbid")


class RecommendationItemCreate(BaseModel):
    """创建推荐项快照的内部 Schema。"""

    recommendation_item_id: str = Field(..., max_length=64, description="推荐项标识")
    recommendation_run_id: str = Field(..., max_length=64, description="所属运行标识")
    case_id: str = Field(..., max_length=64, description="上游案例标识")
    vector_id: str = Field(..., max_length=64, description="向量候选来源标识")
    rank: int = Field(..., ge=1, description="最终排序位置")
    vector_similarity_score: float = Field(..., description="向量相似度分值")
    semantic_similarity_score: Optional[float] = Field(
        None, description="语义重排分值"
    )
    structured_similarity_score: Optional[float] = Field(
        None, description="结构化局部相似度分值"
    )
    business_score: Optional[float] = Field(None, description="业务参数分值")
    final_score: float = Field(..., description="最终聚合分值")
    score_breakdown: dict[str, Any] = Field(..., description="分值来源与权重明细")
    explanation_status: ExplanationStatus = Field(
        ..., description="推荐解释状态"
    )
    missing_fields: list[str] = Field(..., description="候选缺失字段列表")
    case_updated_at: datetime = Field(..., description="候选案例版本")

    @model_validator(mode="after")
    def validate_item_id_not_run_sentinel(self) -> "RecommendationItemCreate":
        """recommendation_item_id 不得等于字面 'RUN'（下游哨兵保留）。"""
        if self.recommendation_item_id == "RUN":
            raise ValueError(
                "recommendation_item_id cannot be literal 'RUN' "
                "(reserved as sentinel for recommendation-feedback)"
            )
        return self

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 内部记录 Schema（仓储层 → 服务层）
# =============================================================================


class RecommendationRunRecord(BaseModel):
    """推荐运行记录。"""

    recommendation_run_id: str = Field(..., description="推荐运行标识")
    query_text_hash: str = Field(..., description="查询文本哈希")
    applied_filters: dict[str, Any] = Field(..., description="规范化过滤条件")
    score_weights: dict[str, float] = Field(..., description="聚合权重配置")
    contract_version: str = Field(..., description="依赖契约版本标识")
    requested_top_k: int = Field(..., description="请求 Top-K")
    returned_count: int = Field(..., description="返回数量")
    vector_candidate_count: int = Field(..., description="向量候选数量")
    status: RunStatus = Field(..., description="运行状态")
    degraded_reason: Optional[str] = Field(None, description="降级原因")
    reranker_model_id: str = Field(..., description="重排模型标识")
    reranker_status: RerankerStatus = Field(..., description="重排状态")
    aggregation_status: AggregationStatus = Field(..., description="聚合状态")
    latency_ms: int = Field(..., description="总耗时")
    error_code: Optional[str] = Field(None, description="错误码")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RecommendationItemRecord(BaseModel):
    """推荐项快照记录。"""

    recommendation_item_id: str = Field(..., description="推荐项标识")
    recommendation_run_id: str = Field(..., description="所属运行标识")
    case_id: str = Field(..., description="上游案例标识")
    vector_id: str = Field(..., description="向量候选来源标识")
    rank: int = Field(..., description="最终排序位置")
    vector_similarity_score: float = Field(..., description="向量相似度分值")
    semantic_similarity_score: Optional[float] = Field(
        None, description="语义重排分值"
    )
    structured_similarity_score: Optional[float] = Field(
        None, description="结构化局部相似度分值"
    )
    business_score: Optional[float] = Field(None, description="业务参数分值")
    final_score: float = Field(..., description="最终聚合分值")
    score_breakdown: dict[str, Any] = Field(..., description="分值来源与权重明细")
    explanation_status: ExplanationStatus = Field(..., description="推荐解释状态")
    missing_fields: list[str] = Field(..., description="候选缺失字段列表")
    case_updated_at: datetime = Field(..., description="候选案例版本")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# =============================================================================
# 错误数据 Schema
# =============================================================================


class RecommendationErrorData(BaseModel):
    """推荐运行错误数据。"""

    error_code: str = Field(..., max_length=64, description="错误码")
    internal_reason: Optional[str] = Field(None, description="内部错误原因")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 运行完成 Result Schema
# =============================================================================


class RunResult(BaseModel):
    """推荐运行完成结果（内部 Schema）。"""

    status: RunStatus = Field(..., description="运行状态")
    returned_count: int = Field(..., description="返回数量")
    vector_candidate_count: int = Field(..., description="向量候选数量")
    reranker_status: RerankerStatus = Field(..., description="重排状态")
    aggregation_status: AggregationStatus = Field(..., description="聚合状态")
    degraded_reason: Optional[str] = Field(None, description="降级原因")
    latency_ms: int = Field(..., description="总耗时")
    items: list["RecommendationItemRecord"] = Field(
        default_factory=list, description="推荐项快照列表"
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# API 响应 Schema
# =============================================================================


class ScoreBreakdownResponse(BaseModel):
    """分值明细响应。"""

    vector_similarity_score: float = Field(..., description="向量相似度原始分")
    semantic_similarity_score: Optional[float] = Field(
        None, description="语义重排原始分"
    )
    structured_similarity_score: Optional[float] = Field(
        None, description="结构化局部相似度原始分"
    )
    business_score: Optional[float] = Field(None, description="业务参数原始分")
    final_score: float = Field(..., description="最终聚合分")
    final_score_source: ScoreBreakdownSource = Field(
        ..., description="最终分值来源标识"
    )
    normalized_scores: dict[str, float] = Field(
        ..., description="归一化分值"
    )
    effective_weights: dict[str, float] = Field(..., description="有效权重")

    model_config = ConfigDict(extra="forbid")


class RecommendationItemResponse(BaseModel):
    """推荐项响应。"""

    recommendation_item_id: str = Field(..., description="推荐项标识")
    case_id: str = Field(..., description="案例标识")
    rank: int = Field(..., description="排序位置")
    case_reference: dict[str, Any] = Field(
        ..., description="案例引用信息"
    )
    core_solution_steps: Optional[str] = Field(None, description="核心解决步骤")
    outcome_summary: Optional[str] = Field(None, description="效果摘要")
    structured_suggestions_summary: Optional[dict[str, Any]] = Field(
        None, description="结构化建议摘要"
    )
    missing_fields: list[str] = Field(..., description="缺失字段列表")
    vector_similarity_score: float = Field(..., description="向量相似度分值")
    semantic_similarity_score: Optional[float] = Field(
        None, description="语义重排分值"
    )
    structured_similarity_score: Optional[float] = Field(
        None, description="结构化局部相似度分值"
    )
    business_score: Optional[float] = Field(None, description="业务参数分值")
    final_score: float = Field(..., description="最终聚合分值")
    score_metadata: ScoreBreakdownResponse = Field(
        ..., description="分值明细元数据"
    )
    recommendation_reason: Optional[str] = Field(
        None, description="推荐理由"
    )
    reference_points: Optional[list[str]] = Field(
        None, description="可参考解决点"
    )
    cautions: Optional[list[str]] = Field(None, description="注意事项")
    source_references: Optional[list[str]] = Field(None, description="来源引用")
    explanation_status: ExplanationStatus = Field(..., description="解释状态")

    model_config = ConfigDict(extra="forbid")


class RecommendationResponse(BaseModel):
    """相似案例推荐响应。"""

    recommendation_run_id: str = Field(..., description="推荐运行标识")
    contract_version: str = Field(..., description="依赖契约版本标识")
    status: RunStatus = Field(..., description="运行状态")
    applied_filters: dict[str, Any] = Field(..., description="应用后的过滤条件")
    score_weights: dict[str, float] = Field(..., description="有效聚合权重")
    query_metadata: dict[str, Any] = Field(
        ..., description="查询元数据"
    )
    items: list[RecommendationItemResponse] = Field(
        ..., description="推荐项列表"
    )
    degraded_reason: Optional[str] = Field(None, description="降级原因")
    error_code: Optional[str] = Field(None, description="错误码")
    message: Optional[str] = Field(None, description="用户可读提示文案")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RecommendationRunResponse(BaseModel):
    """推荐运行响应（GET /api/recommendations/runs/{run_id}）。"""

    recommendation_run_id: str = Field(..., description="推荐运行标识")
    contract_version: str = Field(..., description="依赖契约版本标识")
    query_text_hash: str = Field(..., description="查询文本哈希")
    applied_filters: dict[str, Any] = Field(..., description="应用后的过滤条件")
    score_weights: dict[str, float] = Field(..., description="有效聚合权重")
    requested_top_k: int = Field(..., description="请求 Top-K")
    returned_count: int = Field(..., description="返回数量")
    vector_candidate_count: int = Field(..., description="向量候选数量")
    status: RunStatus = Field(..., description="运行状态")
    degraded_reason: Optional[str] = Field(None, description="降级原因")
    reranker_model_id: str = Field(..., description="重排模型标识")
    reranker_status: RerankerStatus = Field(..., description="重排状态")
    aggregation_status: AggregationStatus = Field(..., description="聚合状态")
    latency_ms: int = Field(..., description="总耗时")
    error_code: Optional[str] = Field(None, description="错误码")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    items: list[RecommendationItemResponse] = Field(
        ..., description="推荐项快照列表"
    )

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# Rebuild forward references
RunResult.model_rebuild()