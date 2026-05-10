"""Embedding 输入组合产物模型（Domain Layer）。"""

from enum import StrEnum
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.vector_indexing.source_models import (
    IndexSourceDegradedReason,
    IndexSourceNotIndexableReason,
)


class EmbeddingSegmentKind(StrEnum):
    """问题侧 embedding 段落类别（与设计文档段落顺序一致）。"""

    PROBLEM_SUMMARY = "problem_summary"
    PROBLEM_DESCRIPTION = "problem_description"
    PROBLEM_TYPE = "problem_type"
    CONTEXT = "context"
    ROOT_CAUSE = "root_cause"
    APPLICABLE_SCENARIOS = "applicable_scenarios"
    TAGS = "tags"
    QUERY_TEXT = "query_text"


class EmbeddingSourceRef(BaseModel):
    """段落内某一上游字段的来源标注。"""

    field_path: str = Field(..., description="契约字段路径")
    version_token: str = Field(
        ...,
        description="来源版本标识（如 enrichment.output_version 或 case.updated_at ISO）",
    )

    model_config = ConfigDict(extra="forbid")


class EmbeddingInputSection(BaseModel):
    """单个语义段落及其来源标注。"""

    kind: EmbeddingSegmentKind
    text: str = Field(default="", description="参与拼接的正文；可为空")
    sources: list[EmbeddingSourceRef] = Field(
        default_factory=list,
        description="该段落文本所依据的上游字段与版本",
    )

    model_config = ConfigDict(extra="forbid")


class EmbeddingInput(BaseModel):
    """供 EmbeddingClient 消费的拼接输入。"""

    text: str = Field(..., description="按稳定顺序拼接的有效段落正文")
    sections: list[EmbeddingInputSection] = Field(
        ...,
        description="固定七段元数据（顺序与设计一致），文本可为空",
    )
    degraded_reason: IndexSourceDegradedReason | None = Field(
        default=None,
        description="采用 Req 1.4 降级路径时沿用快照 degraded_reason",
    )

    model_config = ConfigDict(extra="forbid")


class EmbeddingComposeNotIndexable(BaseModel):
    """快照标明不可索引时的结构化拒绝。"""

    kind: Literal["not_indexable"] = "not_indexable"
    reason: IndexSourceNotIndexableReason

    model_config = ConfigDict(extra="forbid")


class EmbeddingComposeInsufficient(BaseModel):
    """问题侧内容不足以形成可检索文本（Req 1.5）。"""

    kind: Literal["insufficient_content"] = "insufficient_content"
    missing_fields: list[str] = Field(
        ...,
        description="可定位的契约字段路径列表",
    )

    model_config = ConfigDict(extra="forbid")


ComposeCaseInputResult = Union[
    EmbeddingInput,
    EmbeddingComposeNotIndexable,
    EmbeddingComposeInsufficient,
]
