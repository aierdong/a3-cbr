"""LLM 增强请求响应和状态契约。

定义案例增强运行、当前增强状态、人工审核、推荐文案请求响应和错误响应契约。
固化派生结果状态、运行状态、审核状态和输出版本字段。
使用 Pydantic 进行字段校验和类型定义。
"""
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# 枚举定义
# =============================================================================


class EnrichmentStatus(StrEnum):
    """派生结果状态枚举。"""

    VALID = "valid"
    FAILED = "failed"


class RunStatus(StrEnum):
    """增强运行状态枚举。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"
    RETRYABLE = "retryable"


class ErrorStage(StrEnum):
    """错误阶段枚举。"""

    LOAD_CASE = "load_case"
    LLM_CALL = "llm_call"
    PARSE = "parse"
    VALIDATE = "validate"
    PERSIST = "persist"


class DeleteReason(StrEnum):
    """删除原因枚举。"""

    CASE_DELETED = "case_deleted"
    ENRICHMENT_DELETED = "enrichment_deleted"
    VECTOR_DELETED = "vector_deleted"
    FEEDBACK_DELETED = "feedback_deleted"
    SCHEDULE_DELETED = "schedule_deleted"


class RequestedBy(StrEnum):
    """删除者标识枚举。"""

    ANONYMOUS_USER = "anonymous_user"
    SYSTEM = "system"


class BlockingLevel(StrEnum):
    """信息缺失阻断级别枚举。"""

    REQUIRED = "required"
    RECOMMENDED = "recommended"


class TaskType(StrEnum):
    """增强任务类型枚举。"""

    CASE_ENRICHMENT = "case_enrichment"


class RequestPurpose(StrEnum):
    """请求目的枚举。"""

    CASE_ENRICHMENT = "case_enrichment"
    RECOMMENDATION_COPY = "recommendation_copy"


class SourceField(StrEnum):
    """案例源字段枚举，对应 A3Case 的核心内容字段。"""

    PROBLEM_DESCRIPTION = "problem_description"
    CONTEXT = "context"
    ROOT_CAUSE = "root_cause"
    SOLUTION_STEPS = "solution_steps"
    OUTCOME = "outcome"


# =============================================================================
# LLM 输出 Schema（用于 OutputValidator 校验）
# =============================================================================


class MissingInformationItem(BaseModel):
    """信息缺失条目。

    当 LLM 输出无法从案例输入中可靠生成摘要或建议时，
    必须在 missing_information 中返回结构化缺失信息。
    """

    field: SourceField = Field(..., description="缺失信息所属源字段")
    reason: str = Field(..., min_length=1, description="缺失原因说明")
    blocking_level: BlockingLevel = Field(..., description="阻断级别")

    model_config = ConfigDict(extra="forbid")


class StructuredSuggestions(BaseModel):
    """结构化字段建议。

    包含问题类型建议、根因分类、适用场景和置信度说明。
    """

    problem_type_suggestion: str = Field(
        ..., min_length=1, description="问题类型建议",
    )
    root_cause_category: str = Field(
        ..., min_length=1, description="根因类别建议",
    )
    applicable_scenarios: list[str] = Field(
        ..., min_length=1, description="适用场景列表",
    )
    confidence_notes: str = Field(
        ..., description="置信度说明",
    )

    model_config = ConfigDict(extra="forbid")


class TagSuggestion(BaseModel):
    """标签建议。"""

    tag: str = Field(..., min_length=1, description="标签值")

    model_config = ConfigDict(extra="forbid")


class SourceReference(BaseModel):
    """来源字段引用。"""

    field_name: SourceField = Field(..., description="来源字段名")

    model_config = ConfigDict(extra="forbid")


class CaseEnrichmentOutput(BaseModel):
    """LLM 增强输出 Schema。

    用于 OutputValidator 校验 LLM 原始输出。
    missing_information 为必填字段，用于"信息不足"场景的标准返回。
    """

    problem_summary: Optional[str] = Field(None, description="问题摘要")
    solution_summary: Optional[str] = Field(None, description="方案摘要")
    structured_suggestions: StructuredSuggestions = Field(
        ..., description="结构化字段建议",
    )
    tag_suggestions: list[str] = Field(
        ..., min_length=0, description="规范化标签列表",
    )
    source_references: list[SourceField] = Field(
        ..., min_length=0, description="来源字段引用列表",
    )
    missing_information: list[MissingInformationItem] = Field(
        ..., min_length=0, description="信息缺失条目列表",
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 请求 Schema
# =============================================================================


class CreateEnrichmentRunRequest(BaseModel):
    """触发增强运行的请求体。

    MVP 阶段无必填业务字段；预留扩展字段。
    """

    model_config = ConfigDict(extra="allow")


class DeleteEnrichmentRequest(BaseModel):
    """删除增强数据请求。

    至少提供 case_id 或 enrichment_id 之一。
    """

    case_id: Optional[str] = Field(
        None, max_length=64, description="案例标识，按案例删除所有增强数据",
    )
    enrichment_id: Optional[str] = Field(
        None, max_length=64, description="增强标识，删除特定增强记录",
    )
    reason: DeleteReason = Field(..., description="删除原因")
    requested_by: RequestedBy = Field(..., description="删除者标识")

    @model_validator(mode="after")
    def validate_at_least_one_id(self) -> "DeleteEnrichmentRequest":
        """至少提供 case_id 或 enrichment_id 之一。"""
        if not self.case_id and not self.enrichment_id:
            raise ValueError(
                "at least one of case_id or enrichment_id must be provided",
            )
        return self

    model_config = ConfigDict(extra="forbid")


class RecommendationCandidate(BaseModel):
    """推荐候选。"""

    case_id: str = Field(..., min_length=1, max_length=64, description="候选案例标识")
    case_summary: Optional[str] = Field(
        None, description="可选摘要信息，供文案生成使用",
    )
    source_fields: Optional[dict[str, Any]] = Field(
        None, description="可选结构化引用字段快照",
    )

    model_config = ConfigDict(extra="forbid")


class RecommendationCopyRequest(BaseModel):
    """推荐文案请求。"""

    query_text: str = Field(..., min_length=1, description="当前问题文本")
    candidates: list[RecommendationCandidate] = Field(
        ..., min_length=1, description="已排序候选列表",
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 响应 Schema
# =============================================================================


class EnrichmentRunResponse(BaseModel):
    """增强运行响应。"""

    run_id: str = Field(..., description="运行标识")
    case_id: str = Field(..., description="上游案例标识")
    task_type: TaskType = Field(..., description="增强任务类型")
    status: RunStatus = Field(..., description="运行状态")
    model_id: str = Field(..., description="模型标识")
    request_purpose: RequestPurpose = Field(..., description="请求目的")
    case_updated_at: datetime = Field(..., description="输入版本（案例更新时间）")
    error_code: Optional[str] = Field(None, description="失败错误码")
    error_stage: Optional[ErrorStage] = Field(None, description="错误阶段")
    retry_count: int = Field(..., ge=0, description="重试次数")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: Optional[datetime] = Field(None, description="结束时间")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class CaseEnrichmentResultResponse(BaseModel):
    """案例增强派生结果响应。"""

    enrichment_id: str = Field(..., description="派生结果唯一标识")
    case_id: str = Field(..., description="上游案例标识")
    case_updated_at: datetime = Field(
        ..., description="生成所依据的案例更新时间",
    )
    status: EnrichmentStatus = Field(..., description="派生结果状态")
    problem_summary: Optional[str] = Field(None, description="问题摘要")
    solution_summary: Optional[str] = Field(None, description="方案摘要")
    structured_suggestions: dict[str, Any] = Field(
        ..., description="结构化字段建议",
    )
    tag_suggestions: list[str] = Field(
        ..., description="规范化标签列表",
    )
    source_references: list[SourceField] = Field(
        ..., description="来源字段引用列表",
    )
    missing_information: list[MissingInformationItem] = Field(
        default_factory=list, description="信息缺失条目列表",
    )
    output_version: str = Field(..., description="输出 schema 版本")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class CaseEnrichmentStatusResponse(BaseModel):
    """案例当前增强状态响应。"""

    case_id: str = Field(..., description="案例标识")
    latest_run: Optional[EnrichmentRunResponse] = Field(
        None, description="最新增强运行记录",
    )
    current_result: Optional[CaseEnrichmentResultResponse] = Field(
        None, description="当前有效派生结果",
    )

    model_config = ConfigDict(extra="forbid")


class DeleteEnrichmentResponse(BaseModel):
    """删除增强数据响应。"""

    success: bool = Field(..., description="是否成功")
    deleted_count: int = Field(..., ge=0, description="删除的记录数")
    deleted_at: datetime = Field(..., description="删除时间戳")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RecommendationCopyItem(BaseModel):
    """推荐文案项。"""

    case_id: str = Field(..., description="候选案例标识")
    reason: str = Field(..., description="推荐理由")
    reference_points: list[str] = Field(
        ..., description="可参考解决点列表",
    )
    cautions: list[str] = Field(
        ..., description="注意事项列表",
    )
    source_references: list[SourceField] = Field(
        ..., description="来源字段引用列表",
    )

    model_config = ConfigDict(extra="forbid")


class RecommendationCopyResponse(BaseModel):
    """推荐文案响应。"""

    copy_run_id: str = Field(..., description="LLM 文案调用审计标识")
    status: EnrichmentStatus = Field(..., description="生成状态")
    items: list[RecommendationCopyItem] = Field(
        ..., description="推荐文案项列表，保持输入候选顺序",
    )
    schema_validation_status: EnrichmentStatus = Field(
        ..., description="输出 schema 校验状态",
    )
    model_id: Optional[str] = Field(None, description="模型标识")
    request_purpose: Optional[RequestPurpose] = Field(
        None, description="请求目的",
    )
    token_usage: Optional[dict[str, Any]] = Field(
        None, description="成本与用量审计",
    )
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# =============================================================================
# 内部 Schema（服务/仓储层使用）
# =============================================================================


class CaseInputSnapshot(BaseModel):
    """案例输入快照。

    CaseSnapshotProvider 与 EnrichmentService 之间的契约。
    包含 LLM 增强所需的案例基础字段和门店镜像过滤维度。
    """

    case_id: str = Field(..., description="案例标识")
    problem_description: str = Field(..., description="问题描述")
    problem_type: str = Field(..., description="问题类型")
    context: dict[str, Any] = Field(..., description="场景上下文")
    root_cause: str = Field(..., description="根因分析")
    solution_steps: list[dict[str, Any]] = Field(..., description="解决步骤列表")
    outcome: dict[str, Any] = Field(..., description="效果结果")
    status: str = Field(..., description="案例状态")
    updated_at: datetime = Field(..., description="案例更新时间")
    store_id: str = Field(..., description="关联门店 ID")
    store_name: str = Field(..., description="门店名称")
    brand_id: str = Field(..., description="品牌标识")
    brand_name: str = Field(..., description="品牌名称")
    business_type: str = Field(..., description="业态")
    store_scale: str = Field(..., description="门店规模")
    franchise_type: str = Field(..., description="加盟类型")
    city: str = Field(..., description="城市")
    city_tier: str = Field(..., description="城市层级")

    model_config = ConfigDict(extra="forbid")


class EnrichmentRunCreate(BaseModel):
    """创建增强运行记录的内部 Schema。"""

    run_id: str = Field(..., max_length=64, description="运行标识")
    case_id: str = Field(..., max_length=64, description="上游案例标识")
    task_type: TaskType = Field(..., description="增强任务类型")
    status: RunStatus = Field(..., description="运行状态")
    model_id: str = Field(..., max_length=128, description="模型标识")
    request_purpose: RequestPurpose = Field(..., description="请求目的")
    case_updated_at: datetime = Field(..., description="输入版本（案例更新时间）")

    model_config = ConfigDict(extra="forbid")


class CaseEnrichmentResultCreate(BaseModel):
    """创建派生结果的内部 Schema。"""

    enrichment_id: str = Field(..., max_length=64, description="派生结果唯一标识")
    case_id: str = Field(..., max_length=64, description="上游案例标识")
    case_updated_at: datetime = Field(
        ..., description="生成所依据的案例更新时间",
    )
    status: EnrichmentStatus = Field(..., description="派生结果状态")
    problem_summary: Optional[str] = Field(None, description="问题摘要")
    solution_summary: Optional[str] = Field(None, description="方案摘要")
    structured_suggestions: dict[str, Any] = Field(
        ..., description="结构化字段建议",
    )
    tag_suggestions: list[str] = Field(
        ..., description="规范化标签列表",
    )
    source_references: list[SourceField] = Field(
        ..., description="来源字段引用列表",
    )
    missing_information: list[MissingInformationItem] = Field(
        default_factory=list, description="信息缺失条目列表",
    )
    output_version: str = Field(..., max_length=32, description="输出 schema 版本")

    model_config = ConfigDict(extra="forbid")


class EnrichmentErrorData(BaseModel):
    """增强运行错误数据。"""

    error_code: str = Field(..., max_length=64, description="错误码")
    error_stage: ErrorStage = Field(..., description="错误阶段")

    model_config = ConfigDict(extra="forbid")


class DeleteEnrichmentResult(BaseModel):
    """删除增强数据的内部返回结果。"""

    success: bool = Field(..., description="是否成功")
    deleted_count: int = Field(..., ge=0, description="删除的记录数")
    deleted_at: datetime = Field(..., description="删除时间戳")

    model_config = ConfigDict(extra="forbid")


class LLMCompletionRequest(BaseModel):
    """LLM 调用请求。"""

    prompt: str = Field(..., min_length=1, description="完整 prompt 文本")
    model_id: str = Field(..., description="模型标识")
    task_type: TaskType = Field(..., description="任务类型")
    request_purpose: RequestPurpose = Field(..., description="请求目的")
    max_tokens: Optional[int] = Field(None, ge=1, description="最大输出 token 数")
    temperature: Optional[float] = Field(
        None, ge=0.0, le=2.0, description="采样温度",
    )

    model_config = ConfigDict(extra="forbid")


class LLMTokenUsage(BaseModel):
    """LLM token 用量。"""

    prompt_tokens: int = Field(..., ge=0, description="输入 token 数")
    completion_tokens: int = Field(..., ge=0, description="输出 token 数")
    total_tokens: int = Field(..., ge=0, description="总 token 数")

    model_config = ConfigDict(extra="forbid")


class LLMCompletionResult(BaseModel):
    """LLM 调用结果。"""

    content: str = Field(..., description="LLM 输出内容")
    model_id: str = Field(..., description="实际使用的模型标识")
    usage: Optional[LLMTokenUsage] = Field(None, description="token 用量")
    finish_reason: Optional[str] = Field(None, description="完成原因")

    model_config = ConfigDict(extra="forbid")
