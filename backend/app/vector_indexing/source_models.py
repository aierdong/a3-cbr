"""案例向量索引上游快照模型（Integration Layer）。"""

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.cases.schemas import CaseDetailResponse
from app.enrichment.schemas import CaseEnrichmentResultResponse
from app.vector_indexing.schemas import SourceVersion


class IndexSourceNotIndexableReason(StrEnum):
    """上游案例当前不可建立向量索引的原因（只读判定，不写回上游）。"""

    CASE_DELETED = "case_deleted"
    CASE_DRAFT = "case_draft"
    CASE_ARCHIVED = "case_archived"


class IndexSourceDegradedReason(StrEnum):
    """LLM 派生结果不可用时的降级原因（案例仍可尝试降级索引路径）。"""

    ENRICHMENT_MISSING = "enrichment_missing"
    ENRICHMENT_FAILED = "enrichment_failed"


class CaseIndexFilterSnapshot(BaseModel):
    """镜像到向量过滤列的上游字段快照。"""

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


class IndexSourceSnapshot(BaseModel):
    """案例索引输入快照：基础案例 + 过滤镜像 + 可选可消费派生结果 + 来源版本。"""

    case_id: str
    case_detail: Optional[CaseDetailResponse] = Field(
        default=None,
        description="案例详情；删除时不存在",
    )
    filter_fields: Optional[CaseIndexFilterSnapshot] = Field(
        default=None,
        description="过滤字段镜像；删除时不存在",
    )
    case_updated_at: Optional[datetime] = Field(
        default=None,
        description="案例 updated_at；删除时为空",
    )
    enrichment_consumable: Optional[CaseEnrichmentResultResponse] = Field(
        default=None,
        description="当前可消费的 VALID 派生结果",
    )
    source_version: Optional[SourceVersion] = Field(
        default=None,
        description="来源版本（case_updated_at + enrichment 标识/状态）；删除时为空",
    )
    not_indexable_reason: Optional[IndexSourceNotIndexableReason] = None
    degraded_reason: Optional[IndexSourceDegradedReason] = None
    degraded_detail: Optional[str] = Field(
        default=None,
        description="降级或可观测补充说明（不含全文正文）",
    )

    model_config = ConfigDict(extra="forbid")
