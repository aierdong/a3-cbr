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
from typing import Annotated, Any, Optional

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
# 请求、过滤与查询 Schema
# =============================================================================


class RetrievalFilters(BaseModel):
    """检索过滤条件。

    支持品牌、门店、问题类型、标签、案例状态和创建时间范围等基础过滤条件。
    """

    brand_id: Optional[str] = Field(None, max_length=64, description="品牌标识")
    store_id: Optional[str] = Field(None, max_length=64, description="门店标识")
    problem_type: Optional[str] = Field(None, max_length=128, description="问题类型")
    tags: Optional[list[str]] = Field(default=None, description="标签列表")
    case_status: Optional[str] = Field(None, max_length=32, description="案例状态")
    created_at_from: Optional[datetime] = Field(None, description="创建时间范围起始")
    created_at_to: Optional[datetime] = Field(None, description="创建时间范围结束")

    model_config = ConfigDict(extra="forbid")


class BusinessWeights(BaseModel):
    """业务权重参数。

    用于调整不同业务因子在最终排序中的权重。
    """

    business_type_weight: Annotated[float, Field(ge=0, le=1, description="业态权重")] = 0.2
    store_tier_weight: Annotated[float, Field(ge=0, le=1, description="门店等级权重")] = 0.15
    brand_affinity_weight: Annotated[float, Field(ge=0, le=1, description="品牌亲和度权重")] = 0.1
    recency_weight: Annotated[float, Field(ge=0, le=1, description="时间接近度权重")] = 0.05

    model_config = ConfigDict(extra="forbid")


class RetrievalRequest(BaseModel):
    """相似案例推荐请求。

    包含当前问题文本、Top-K 参数、可选过滤条件和可选业务权重参数。
    """

    query_text: str = Field(..., min_length=1, max_length=2000, description="当前问题文本")
    top_k: Annotated[int, Field(gt=0, le=100, description="推荐数量上限")] = 10
    filters: Optional[RetrievalFilters] = Field(default=None, description="过滤条件")
    business_weights: Optional[BusinessWeights] = Field(default=None, description="业务权重参数")

    model_config = ConfigDict(extra="forbid")


class QueryStructuredSuggestions(BaseModel):
    """查询侧结构化画像。

    LLM normalizer 单次外呼产出的查询侧结构化画像，用于后续结构化局部相似度评分。
    MVP 可不纳入评分，但该字段在 LLM normalizer 成功时仍应落地。
    """

    suggested_problem_type: Optional[str] = Field(None, description="建议问题类型")
    suggested_root_cause_category: Optional[str] = Field(None, description="建议根因分类")
    suggested_applicable_scenes: Optional[list[str]] = Field(
        default=None, description="建议适用场景"
    )
    suggested_tags: Optional[list[str]] = Field(default=None, description="建议标签")

    model_config = ConfigDict(extra="forbid")


class NormalizedRetrievalQuery(BaseModel):
    """标准化检索查询。

    由 schema 校验后的请求字段与单次 LLM normalizer 输出合并而成。
    包含标准化检索文本与查询侧结构化画像。
    """

    normalized_query_text: str = Field(..., description="标准化检索文本（用于向量搜索和 reranker）")
    query_structured_suggestions: QueryStructuredSuggestions = Field(
        ..., description="查询侧结构化画像"
    )
    applied_filters: dict[str, Any] = Field(..., description="规范化后的过滤条件")
    effective_weights: dict[str, float] = Field(..., description="有效业务权重")
    top_k: int = Field(..., description="Top-K 参数")

    model_config = ConfigDict(extra="forbid")


class CandidateSnapshot(BaseModel):
    """推荐候选案例快照。

    从向量搜索候选和案例详情补齐后组装，供评分和聚合使用。
    """

    case_id: str = Field(..., description="案例标识")
    vector_id: str = Field(..., description="向量标识")
    vector_similarity_score: float = Field(..., description="向量相似度分值")
    problem_summary: Optional[str] = Field(None, description="问题摘要")
    problem_description: Optional[str] = Field(None, description="问题描述")
    core_solution_steps: Optional[str] = Field(None, description="核心解决步骤")
    outcome_summary: Optional[str] = Field(None, description="效果摘要")
    structured_suggestions: Optional[dict[str, Any]] = Field(None, description="结构化建议")
    brand_id: Optional[str] = Field(None, description="品牌标识")
    store_id: Optional[str] = Field(None, description="门店标识")
    problem_type: Optional[str] = Field(None, description="问题类型")
    tags: Optional[list[str]] = Field(default=None, description="标签列表")
    case_status: Optional[str] = Field(None, description="案例状态")
    case_updated_at: datetime = Field(..., description="案例更新时间")

    model_config = ConfigDict(extra="forbid")


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


class ValidationErrorDetail(BaseModel):
    """字段级验证错误详情。"""

    field: str = Field(..., description="错误字段路径")
    message: str = Field(..., description="错误信息")

    model_config = ConfigDict(extra="forbid")


class ValidationErrorResponse(BaseModel):
    """请求验证失败响应（422）。"""

    error_code: str = Field(default="VALIDATION_ERROR", description="错误码")
    message: str = Field(default="请求参数验证失败", description="错误描述")
    details: list[ValidationErrorDetail] = Field(..., description="字段级错误详情")

    model_config = ConfigDict(extra="forbid")


class SummarizationFailedResponse(BaseModel):
    """LLM normalizer 失败响应（503）。

    用于 Requirement 1.7 fail closed 场景。
    """

    recommendation_run_id: str = Field(..., description="推荐运行标识")
    error_code: str = Field(default="QUERY_SUMMARIZATION_FAILED", description="错误码")
    status: RunStatus = Field(default=RunStatus.FAILED, description="运行状态")
    message: str = Field(
        default="当前无法理解您的问题，请稍后重试", description="用户可读提示文案"
    )
    summarization_status: str = Field(
        default="failed", description="摘要生成状态"
    )

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


class DegradedStatus(StrEnum):
    """降级状态枚举。

    用于描述推荐流程中的降级原因。
    """

    RERANKER_FAILED = "reranker_failed"
    AGGREGATION_FAILED = "aggregation_failed"
    RERANKER_AND_AGGREGATION_FAILED = "reranker_and_aggregation_failed"
    EXPLANATION_FALLBACK = "explanation_fallback"
    PARTIAL_CANDIDATE_DATA = "partial_candidate_data"
    NO_CANDIDATES = "no_candidates"


class DegradedRankingResponse(BaseModel):
    """降级排序响应。"""

    fallback_ranking_source: str = Field(..., description="降级排序来源")
    reranker_status: RerankerStatus = Field(..., description="重排状态")
    aggregation_status: AggregationStatus = Field(..., description="聚合状态")
    degraded_reason: str = Field(..., description="降级原因")

    model_config = ConfigDict(extra="forbid")


# Rebuild forward references
RunResult.model_rebuild()