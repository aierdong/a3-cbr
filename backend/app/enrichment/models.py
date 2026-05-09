"""案例增强派生结果、运行记录和推荐文案运行 ORM 模型。

本模块定义 LLM 增强相关的三张表：
- case_enrichment_results: 案例增强派生结果（每案例唯一）
- case_enrichment_runs: 案例增强运行记录（每次增强尝试）
- recommendation_copy_runs: 推荐文案 LLM 调用审计记录
"""

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)

from app.db.base import Base


class CaseEnrichmentResult(Base):
    """案例增强派生结果表。

    每个案例只有一条有效的派生结果记录（通过 UNIQUE(case_id) 保证）。
    包含问题摘要、方案摘要、结构化建议、标签建议和来源引用。
    """

    __tablename__ = "case_enrichment_results"

    enrichment_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    case_updated_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False)  # valid / failed
    problem_summary = Column(Text, nullable=True)
    solution_summary = Column(Text, nullable=True)
    structured_suggestions = Column(JSON, nullable=False)  # JSONB
    tag_suggestions = Column(JSON, nullable=False)  # JSONB
    source_references = Column(JSON, nullable=False)  # JSONB
    output_version = Column(String(32), nullable=False)
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
        UniqueConstraint("case_id", name="uq_case_enrichment_results_case_id"),
        Index("ix_case_enrichment_results_case_id_status", "case_id", "status"),
        Index(
            "ix_case_enrichment_results_case_id_updated",
            "case_id",
            "case_updated_at",
        ),
    )


class CaseEnrichmentRun(Base):
    """案例增强运行记录表。

    记录每次增强尝试的生命周期：运行状态、模型标识、请求目的、
    错误阶段和重试次数。
    """

    __tablename__ = "case_enrichment_runs"

    run_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    task_type = Column(String(64), nullable=False)  # case_enrichment
    # running/succeeded/failed/validation_failed/retryable
    status = Column(String(32), nullable=False, index=True)
    model_id = Column(String(128), nullable=False)
    request_purpose = Column(String(128), nullable=False)
    case_updated_at = Column(DateTime(timezone=True), nullable=False)
    error_code = Column(String(64), nullable=True)
    error_stage = Column(String(32), nullable=True)  # load_case/llm_call/parse/validate/persist
    retry_count = Column(Integer, nullable=False, default=0)
    started_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_case_enrichment_runs_case_id_started",
            "case_id",
            desc("started_at"),
        ),
    )


class RecommendationCopyRun(Base):
    """推荐文案 LLM 调用审计记录表。

    仅记录 LLM 调用审计、成本和 schema 校验结果，不作为推荐运行、
    召回或排序持久化记录。
    """

    __tablename__ = "recommendation_copy_runs"

    copy_run_id = Column(String(64), primary_key=True)
    query_text_hash = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, index=True)  # succeeded / failed
    candidate_case_ids = Column(JSON, nullable=False)  # JSONB
    items = Column(JSON, nullable=False)  # JSONB
    model_id = Column(String(128), nullable=False)
    request_purpose = Column(String(128), nullable=False)
    token_usage = Column(JSON, nullable=True)  # JSONB
    schema_validation_status = Column(String(32), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
