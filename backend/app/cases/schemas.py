"""案例请求响应数据契约。

定义 A3 案例管理的创建、编辑、删除、详情、列表请求响应结构。
使用 Pydantic 进行字段校验和类型定义。
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeleteCaseReason(str, Enum):
    """删除原因枚举。"""

    USER_REQUESTED = "user_requested"  # 用户主动删除
    STORE_CLOSED = "store_closed"  # 门店关闭
    DATA_CORRECTED = "data_corrected"  # 数据纠错
    DUPLICATE = "duplicate"  # 重复案例
    POLICY_VIOLATION = "policy_violation"  # 违反政策
    OTHER = "other"  # 其他原因


class OutcomeResult(str, Enum):
    """效果结果枚举。"""

    IMPROVED = "improved"  # 已改善
    NO_CHANGE = "no_change"  # 无明显改善
    UNKNOWN = "unknown"  # 未评估/暂不可得


class ProblemType(str, Enum):
    """问题类型枚举（MVP 受控枚举）。"""

    SERVICE_QUALITY = "service_quality"
    OPERATIONS = "operations"
    STAFF_TRAINING = "staff_training"
    EQUIPMENT_MAINTENANCE = "equipment_maintenance"


class CaseStatus(str, Enum):
    """案例状态枚举。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


# =============================================================================
# JSONB 字段 Schema
# =============================================================================


class SolutionStepSchema(BaseModel):
    """解决步骤 Schema。

    solution_steps 数组元素结构。
    - order: 从 1 开始，连续递增
    - content: 非空，可读文本
    """

    order: int = Field(..., ge=1, description="步骤顺序，从 1 开始")
    content: str = Field(..., min_length=1, description="步骤内容")

    model_config = ConfigDict(extra="allow")


class ContextSchema(BaseModel):
    """场景上下文 Schema。

    context jsonb 最小键集合。
    - scene: 场景/问题背景的简要归类或描述
    """

    scene: str = Field(..., min_length=1, description="场景描述")
    # 允许扩展字段，如 shift, weather, staffing, equipment 等

    model_config = ConfigDict(extra="allow")


class OutcomeSchema(BaseModel):
    """效果结果 Schema。

    outcome jsonb 最小键集合。
    - result: improved | no_change | unknown
    - notes: 允许为空，但字段必须存在
    """

    result: OutcomeResult = Field(..., description="效果结果")
    notes: str = Field(default="", description="效果备注")

    model_config = ConfigDict(extra="allow")


# =============================================================================
# 门店信息 Schema
# =============================================================================


class StoreInfoSummary(BaseModel):
    """门店信息摘要（用于详情和列表响应关联返回）。"""

    store_id: str = Field(..., description="门店主键")
    store_name: str = Field(..., description="门店名称")
    brand_id: str = Field(..., description="品牌标识")
    brand_name: str = Field(..., description="品牌名称")
    business_type: str = Field(..., description="业态")
    store_scale: str = Field(..., description="门店规模")
    franchise_type: str = Field(..., description="加盟类型")
    city: str = Field(..., description="城市")
    city_tier: str = Field(..., description="城市规模")
    updated_at: datetime = Field(..., description="镜像行更新时间")

    model_config = ConfigDict(extra="allow")


# =============================================================================
# 创建 & 编辑请求
# =============================================================================


class CreateCaseRequest(BaseModel):
    """创建案例请求。

    必填字段：problem_description, store_id, problem_type,
              context, root_cause, solution_steps, outcome
    可选：status（仅 draft 或 active，默认 draft）
    不包含：case_id, created_at, updated_at
    """

    problem_description: str = Field(..., min_length=1, description="问题描述")
    store_id: str = Field(
        ...,
        min_length=1,
        description="关联门店 ID（引用已存在的 store_infos.store_id）",
    )
    problem_type: ProblemType = Field(..., description="问题类型")
    context: ContextSchema = Field(..., description="场景上下文")
    root_cause: str = Field(..., min_length=1, description="根因分析")
    solution_steps: list[SolutionStepSchema] = Field(
        ...,
        min_length=1,
        description="有序解决步骤列表",
    )
    outcome: OutcomeSchema = Field(..., description="效果结果")
    status: CaseStatus = Field(
        default=CaseStatus.DRAFT,
        description="创建时初始状态，仅允许 draft 或 active",
    )

    # 禁止字段：case_id, created_at, updated_at
    case_id: None = Field(None, description="禁止字段")
    created_at: None = Field(None, description="禁止字段")
    updated_at: None = Field(None, description="禁止字段")

    @model_validator(mode="after")
    def reject_archived_on_create(self) -> "CreateCaseRequest":
        """创建时不允许直接以 archived 落库。"""
        if self.status == CaseStatus.ARCHIVED:
            raise ValueError("status on create must be draft or active, not archived")
        return self

    @field_validator("solution_steps")
    @classmethod
    def validate_solution_steps_order(
        cls, v: list[SolutionStepSchema],
    ) -> list[SolutionStepSchema]:
        """校验步骤顺序连续且从 1 开始。"""
        orders = [step.order for step in v]
        expected = list(range(1, len(v) + 1))
        if orders != expected:
            raise ValueError(
                "solution_steps order must be consecutive starting from 1,"
                f" got {orders}",
            )
        return v

    model_config = ConfigDict(extra="forbid")


class UpdateCaseRequest(BaseModel):
    """编辑案例请求。

    可编辑字段：problem_description, store_id, problem_type,
                context, root_cause, solution_steps, outcome, status
    禁止字段：case_id, created_at
    所有字段均为可选。
    """

    problem_description: Optional[str] = Field(None, min_length=1, description="问题描述")
    store_id: Optional[str] = Field(None, min_length=1, description="关联门店 ID")
    problem_type: Optional[ProblemType] = Field(None, description="问题类型")
    context: Optional[ContextSchema] = Field(None, description="场景上下文")
    root_cause: Optional[str] = Field(None, min_length=1, description="根因分析")
    solution_steps: Optional[list[SolutionStepSchema]] = Field(
        None, min_length=1, description="有序解决步骤",
    )
    outcome: Optional[OutcomeSchema] = Field(None, description="效果结果")
    status: Optional[CaseStatus] = Field(None, description="案例状态")

    # 禁止字段
    case_id: None = Field(None, description="禁止字段")
    created_at: None = Field(None, description="禁止字段")

    @field_validator("solution_steps")
    @classmethod
    def validate_solution_steps_order(
        cls, v: Optional[list[SolutionStepSchema]],
    ) -> Optional[list[SolutionStepSchema]]:
        """校验步骤顺序连续且从 1 开始。"""
        if v is None:
            return v
        orders = [step.order for step in v]
        expected = list(range(1, len(v) + 1))
        if orders != expected:
            raise ValueError(
                "solution_steps order must be consecutive starting from 1,"
                f" got {orders}",
            )
        return v

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 详情 & 列表响应
# =============================================================================


class CaseDetailResponse(BaseModel):
    """案例详情响应。

    包含全部基础字段和关联的 StoreInfo 字段。
    tag_suggestions 来自 llm-case-enrichment 派生结果（规范化标签字符串数组）。
    排除：embedding, summary, recommendation_reason,
          similarity_score, feedback
    """

    case_id: str = Field(..., description="案例标识")
    problem_description: str = Field(..., description="问题描述")
    store_id: str = Field(..., description="关联门店 ID")
    problem_type: ProblemType = Field(..., description="问题类型")
    context: ContextSchema = Field(..., description="场景上下文")
    root_cause: str = Field(..., description="根因分析")
    solution_steps: list[SolutionStepSchema] = Field(..., description="有序解决步骤")
    outcome: OutcomeSchema = Field(..., description="效果结果")
    status: CaseStatus = Field(..., description="案例状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    store: StoreInfoSummary = Field(..., description="关联门店信息")
    tag_suggestions: list[str] = Field(
        default_factory=list,
        description="LLM 规范化标签建议（案例增强）；无增强结果时为空数组",
    )

    model_config = ConfigDict(extra="forbid")


class CaseListItem(BaseModel):
    """案例列表项。

    包含足够摘要字段供前端展示和下游检索入口选择。
    排除派生字段。
    """

    case_id: str = Field(..., description="案例标识")
    problem_description: str = Field(..., description="问题描述（摘要）")
    store_id: str = Field(..., description="关联门店 ID")
    problem_type: ProblemType = Field(..., description="问题类型")
    context: ContextSchema = Field(..., description="场景上下文（含 scene，供列表场景列展示）")
    status: CaseStatus = Field(..., description="案例状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    store: StoreInfoSummary = Field(..., description="关联门店信息")

    model_config = ConfigDict(extra="forbid")


class CaseListQuery(BaseModel):
    """案例列表查询参数。"""

    # 分页参数
    limit: int = Field(default=20, ge=1, le=100, description="每页数量")
    cursor_created_at: Optional[datetime] = Field(None, description="分页游标：创建时间")
    cursor_case_id: Optional[str] = Field(None, description="分页游标：案例 ID")
    include_archived: bool = Field(default=False, description="是否包含归档案例")

    # 过滤参数
    brand_id: Optional[str] = Field(None, description="品牌标识过滤")
    store_id: Optional[str] = Field(None, description="门店 ID 过滤")
    business_type: Optional[str] = Field(None, description="业态过滤")
    store_scale: Optional[str] = Field(None, description="门店规模过滤")
    franchise_type: Optional[str] = Field(None, description="加盟类型过滤")
    city: Optional[str] = Field(None, description="城市过滤")
    city_tier: Optional[str] = Field(None, description="城市规模过滤")
    problem_type: Optional[ProblemType] = Field(None, description="问题类型过滤")
    status: Optional[CaseStatus] = Field(None, description="状态过滤")
    created_after: Optional[datetime] = Field(None, description="创建时间范围起点")
    created_before: Optional[datetime] = Field(None, description="创建时间范围终点")

    @model_validator(mode="after")
    def validate_cursor_pair(self) -> "CaseListQuery":
        """cursor_created_at 和 cursor_case_id 必须成对提供或成对省略。"""
        has_cursor_time = self.cursor_created_at is not None
        has_cursor_id = self.cursor_case_id is not None
        if has_cursor_time != has_cursor_id:
            raise ValueError(
                "cursor_created_at and cursor_case_id must be provided"
                " together or both omitted",
            )
        return self

    model_config = ConfigDict(extra="forbid")


class PaginatedCaseListResponse(BaseModel):
    """分页案例列表响应。"""

    items: list[CaseListItem] = Field(..., description="案例列表项")
    limit: int = Field(..., description="请求的每页数量")
    next_cursor_created_at: Optional[datetime] = Field(
        None, description="下一页游标：创建时间",
    )
    next_cursor_case_id: Optional[str] = Field(
        None, description="下一页游标：案例 ID",
    )
    has_more: bool = Field(..., description="是否还有更多数据")
    sort: str = Field(
        default="created_at desc, case_id desc",
        description="排序方式",
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# 删除请求 & 响应
# =============================================================================


class DeleteCaseRequest(BaseModel):
    """基础删除案例请求。"""

    case_id: str = Field(..., min_length=1, description="待删除案例 ID")
    reason: DeleteCaseReason = Field(..., description="删除原因")
    requested_by: str = Field(..., min_length=1, description="删除者标识")

    model_config = ConfigDict(extra="forbid")


class DeleteCaseResponse(BaseModel):
    """基础删除案例响应。"""

    success: bool = Field(..., description="是否成功")
    deleted_count: int = Field(..., ge=0, description="删除数量")
    deleted_at: datetime = Field(..., description="删除时间")

    model_config = ConfigDict(extra="forbid")


class CascadeDeleteRequest(BaseModel):
    """级联删除案例请求。"""

    case_id: str = Field(..., min_length=1, description="待删除案例 ID")
    requested_by: str = Field(..., min_length=1, description="删除者标识")

    model_config = ConfigDict(extra="forbid")


class CascadeDeleteSubFailure(BaseModel):
    """级联删除子步骤失败详情。"""

    service: str = Field(..., description="失败的服务名称")
    error: str = Field(..., description="错误描述")

    model_config = ConfigDict(extra="forbid")


class CascadeDeleteResponse(BaseModel):
    """级联删除案例响应。"""

    success: bool = Field(..., description="整体是否成功")
    case_id: str = Field(..., description="被删除的案例 ID")
    case_deleted: bool = Field(..., description="案例基础数据是否已删除")
    enrichment_deleted: bool = Field(..., description="LLM 增强数据是否已删除")
    vector_deleted: bool = Field(..., description="向量索引数据是否已删除")
    feedback_deleted: bool = Field(..., description="推荐反馈数据是否已删除")
    case_deleted_count: int = Field(..., ge=0, description="案例删除数量")
    enrichment_deleted_count: int = Field(..., ge=0, description="增强数据删除数量")
    vector_deleted_count: int = Field(..., ge=0, description="向量索引删除数量")
    feedback_deleted_count: int = Field(..., ge=0, description="反馈数据删除数量")
    partial_failures: list[CascadeDeleteSubFailure] = Field(
        default_factory=list,
        description="部分失败详情列表",
    )

    model_config = ConfigDict(extra="forbid")
