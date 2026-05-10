"""向量索引 API 请求/响应 schema 与状态枚举。

契约优先对齐 docs/contracts/case-vector-indexing.openapi.yaml；
级联删除请求/响应对齐 case-vector-indexing design.md。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VectorJobType(str, Enum):
    """向量索引任务类型（API 层）。"""

    REFRESH = "refresh"
    RETRY = "retry"
    REMOVE = "remove"


class VectorJobStatus(str, Enum):
    """向量索引任务状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYABLE = "retryable"
    CANCELLED = "cancelled"


class VectorErrorStage(str, Enum):
    """失败阶段（与任务记录的 error_stage 一致）。"""

    LOAD_SOURCE = "load_source"
    COMPOSE_INPUT = "compose_input"
    EMBEDDING_CALL = "embedding_call"
    VALIDATE_EMBEDDING = "validate_embedding"
    PERSIST = "persist"


class VectorIndexStatus(str, Enum):
    """案例向量索引聚合状态（状态查询接口）。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    FAILED = "failed"
    PUBLISHED = "published"
    DEGRADED = "degraded"
    UNSEARCHABLE = "unsearchable"


class MarkVectorUnsearchableReason(str, Enum):
    """标记不可检索原因（契约枚举子集；允许任意字符串以兼容扩展）。"""

    CASE_DELETED = "case_deleted"
    CASE_ARCHIVED = "case_archived"
    SOURCE_NOT_ALLOWED = "source_not_allowed"
    MANUAL_ADMIN_ACTION = "manual_admin_action"


class DeleteVectorIndexReason(str, Enum):
    """级联删除向量索引的原因（design.md）。"""

    CASE_DELETED = "case_deleted"
    ENRICHMENT_DELETED = "enrichment_deleted"
    VECTOR_DELETED = "vector_deleted"
    FEEDBACK_DELETED = "feedback_deleted"
    SCHEDULE_DELETED = "schedule_deleted"


class RefreshVectorIndexRequest(BaseModel):
    """手动刷新向量索引请求。"""

    force_rebuild: bool = Field(default=False, description="为 true 时跳过版本短路并强制刷新")
    requested_by: Optional[str] = Field(default=None, description="触发来源标识")

    model_config = ConfigDict(extra="allow")


class MarkVectorUnsearchableRequest(BaseModel):
    """标记案例向量不可检索请求。"""

    reason: str = Field(..., min_length=1, description="不可检索原因")
    requested_by: Optional[str] = Field(default=None, description="操作发起方标识")

    model_config = ConfigDict(extra="forbid")


class SourceVersion(BaseModel):
    """刷新幂等判断用的来源版本快照。"""

    case_updated_at: datetime
    enrichment_id: Optional[str] = None
    enrichment_status: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class VectorIndexJobResponse(BaseModel):
    """向量索引任务响应（刷新、重试等）。"""

    job_id: str = Field(..., max_length=64)
    case_id: str = Field(..., max_length=64)
    job_type: VectorJobType
    status: VectorJobStatus
    source_version: Optional[SourceVersion] = None
    error_code: Optional[str] = None
    error_stage: Optional[VectorErrorStage] = None
    retry_count: int = Field(..., ge=0)
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")


class CaseVectorRecord(BaseModel):
    """当前向量记录摘要（API 契约；不等同于 ORM 全字段）。"""

    vector_id: str
    case_id: str
    case_updated_at: datetime
    enrichment_id: Optional[str] = None
    enrichment_status: Optional[str] = None
    input_template_version: str
    input_content_hash: str
    embedding_model_id: str
    embedding_dimension: int = Field(..., ge=1)
    is_current: bool
    searchable: bool
    degraded_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class VectorIndexStatusResponse(BaseModel):
    """案例向量索引状态查询响应。"""

    case_id: str = Field(..., max_length=64)
    status: VectorIndexStatus
    latest_job: Optional[VectorIndexJobResponse] = None
    current_vector: Optional[CaseVectorRecord] = None
    last_error_code: Optional[str] = None
    message: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class DeleteVectorIndexRequest(BaseModel):
    """按案例或向量标识删除索引（级联删除契约）。"""

    case_id: Optional[str] = Field(default=None, max_length=64)
    vector_id: Optional[str] = Field(default=None, max_length=64)
    reason: DeleteVectorIndexReason
    requested_by: str = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_case_or_vector(self) -> "DeleteVectorIndexRequest":
        if self.case_id is None and self.vector_id is None:
            raise ValueError("case_id 与 vector_id 至少填写其一")
        return self


class DeleteVectorIndexResponse(BaseModel):
    """删除向量索引响应（幂等）。"""

    success: bool
    deleted_count: int = Field(..., ge=0)
    deleted_at: datetime

    model_config = ConfigDict(extra="forbid")


class VectorSearchFilters(BaseModel):
    """结构化过滤条件。"""

    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    business_type: Optional[str] = None
    store_scale: Optional[str] = None
    franchise_type: Optional[str] = None
    city: Optional[str] = None
    city_tier: Optional[str] = None
    problem_type: Optional[str] = None
    tags: Optional[list[str]] = None
    case_status: Optional[str] = None
    created_at_from: Optional[datetime] = None
    created_at_to: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")


class VectorSearchRequest(BaseModel):
    """向量搜索请求。"""

    query_text: str = Field(..., min_length=1)
    top_k: int = Field(default=20, ge=1, le=100)
    filters: Optional[VectorSearchFilters] = None
    include_metadata: bool = False

    model_config = ConfigDict(extra="forbid")


class VectorCandidateFilterMetadata(BaseModel):
    """候选案例过滤元数据（供下游检索编排使用）。"""

    brand_id: str
    store_id: str
    business_type: str
    store_scale: str
    franchise_type: str
    city: str
    city_tier: str
    problem_type: str
    tags: list[str]
    case_status: str

    model_config = ConfigDict(extra="forbid")


class VectorSearchCandidate(BaseModel):
    """单个语义检索候选。"""

    case_id: str
    vector_id: str
    similarity_score: float
    distance: float
    case_updated_at: datetime
    input_content_hash: str
    filter_metadata: VectorCandidateFilterMetadata

    model_config = ConfigDict(extra="forbid")


class VectorSearchQueryMetadata(BaseModel):
    """搜索批次查询侧元数据。"""

    query_hash: str
    model_id: str
    dimension: int = Field(..., ge=1)
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    total_candidates_considered: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class VectorSearchResponse(BaseModel):
    """向量搜索结果。"""

    items: list[VectorSearchCandidate]
    query_metadata: VectorSearchQueryMetadata

    model_config = ConfigDict(extra="forbid")
