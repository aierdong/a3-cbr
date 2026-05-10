"""向量仓储层输入/输出契约（与 API schemas 解耦，字段对齐 case_vectors / vector_index_jobs）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaseVectorCreate(BaseModel):
    """写入 case_vectors 的一条成功案例向量。"""

    vector_id: str = Field(..., max_length=64)
    case_id: str = Field(..., max_length=64)
    case_updated_at: datetime
    enrichment_id: Optional[str] = Field(default=None, max_length=64)
    enrichment_status: Optional[str] = Field(default=None, max_length=32)
    embedding_model_id: str = Field(..., max_length=128)
    embedding_dimension: int = Field(..., ge=1)
    embedding_vector: list[float]
    brand_id: str = Field(..., max_length=64)
    store_id: str = Field(..., max_length=64)
    problem_type: str = Field(..., max_length=64)
    tags: list[str] = Field(default_factory=list)
    case_status: str = Field(..., max_length=32)
    degraded_reason: Optional[str] = Field(default=None, max_length=256)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _embedding_length_matches_dimension(self) -> CaseVectorCreate:
        if len(self.embedding_vector) != self.embedding_dimension:
            raise ValueError("embedding_vector 长度必须与 embedding_dimension 一致")
        return self


class CaseVectorPersisted(BaseModel):
    """仓储返回的向量行快照（不含隐私正文）。"""

    vector_id: str
    case_id: str
    case_updated_at: datetime
    enrichment_id: Optional[str] = None
    enrichment_status: Optional[str] = None
    embedding_model_id: str
    embedding_dimension: int
    embedding_vector: list[float]
    brand_id: str
    store_id: str
    problem_type: str
    tags: list[str]
    case_status: str
    degraded_reason: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class VectorIndexJobCreate(BaseModel):
    """新建 vector_index_jobs 行。"""

    job_id: str = Field(..., max_length=64)
    case_id: str = Field(..., max_length=64)
    job_type: str = Field(..., max_length=32)
    status: str = Field(..., max_length=32)
    source_version: Optional[dict[str, Any]] = None
    retry_count: int = Field(default=0, ge=0)
    old_vector_id: Optional[str] = Field(default=None, max_length=64)
    old_content_hash: Optional[str] = Field(default=None, max_length=128)
    new_vector_id: Optional[str] = Field(default=None, max_length=64)
    error_code: Optional[str] = Field(default=None, max_length=64)
    error_stage: Optional[str] = Field(default=None, max_length=32)
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")


class VectorIndexJobPatch(BaseModel):
    """更新已有任务的可变字段。"""

    status: Optional[str] = Field(default=None, max_length=32)
    source_version: Optional[dict[str, Any]] = None
    old_vector_id: Optional[str] = Field(default=None, max_length=64)
    old_content_hash: Optional[str] = Field(default=None, max_length=128)
    new_vector_id: Optional[str] = Field(default=None, max_length=64)
    error_code: Optional[str] = Field(default=None, max_length=64)
    error_stage: Optional[str] = Field(default=None, max_length=32)
    retry_count: Optional[int] = Field(default=None, ge=0)
    next_retry_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")


class VectorIndexJobRecord(BaseModel):
    """任务行读取模型。"""

    job_id: str
    case_id: str
    job_type: str
    status: str
    source_version: Optional[dict[str, Any]] = None
    old_vector_id: Optional[str] = None
    old_content_hash: Optional[str] = None
    new_vector_id: Optional[str] = None
    error_code: Optional[str] = None
    error_stage: Optional[str] = None
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class VectorCandidateFilterPayload(BaseModel):
    """候选过滤元数据：表中仅有部分列，其余占位以满足下游契约拼装。"""

    brand_id: str
    store_id: str
    business_type: str = ""
    store_scale: str = ""
    franchise_type: str = ""
    city: str = ""
    city_tier: str = ""
    problem_type: str
    tags: list[str]
    case_status: str

    model_config = ConfigDict(extra="forbid")


class VectorCandidateRecord(BaseModel):
    """单次向量搜索结果（搜索原语层）。"""

    case_id: str
    vector_id: str
    similarity_score: float
    distance: float
    case_updated_at: datetime
    input_content_hash: str = ""
    filter_metadata: VectorCandidateFilterPayload

    model_config = ConfigDict(extra="forbid")


class VectorSearchQuery(BaseModel):
    """仓储搜索参数（已由上层完成查询向量生成）。"""

    query_embedding: list[float]
    top_k: int = Field(..., ge=1, le=500)
    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    problem_type: Optional[str] = None
    tags: Optional[list[str]] = None
    case_status: Optional[str] = None
    case_updated_at_from: Optional[datetime] = None
    case_updated_at_to: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")
