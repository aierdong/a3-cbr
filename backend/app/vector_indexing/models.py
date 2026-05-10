"""向量索引 ORM 模型。

定义 case_vectors 和 vector_index_jobs 两张表及其索引：
- case_vectors: 保存成功案例向量、过滤字段、来源版本和生命周期
- vector_index_jobs: 保存向量索引任务生命周期、审计字段和重试元数据

设计约束：
- 每个案例最多一条向量记录（case_id UNIQUE 约束）
- 使用 pgvector.sqlalchemy.Vector(dim) 类型定义 embedding_vector 列
- HNSW 索引使用 cosine 操作符，支持语义相似度搜索
"""

from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.db.base import Base


class EmbeddingJobStatus(str, Enum):
    """向量索引任务状态枚举。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EnrichmentStatus(str, Enum):
    """向量索引来源 enrichment 状态枚举。"""

    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class VectorIndexJobType(str, Enum):
    """向量索引任务类型枚举。"""

    INDEX = "index"
    REFRESH = "refresh"
    RETRY = "retry"
    REMOVE = "remove"


class CaseVector(Base):
    """案例向量记录表。

    保存成功生成的问题侧语义向量、结构化过滤字段和来源版本。
    每个案例最多一条向量记录（通过 case_id UNIQUE 约束保证）。

    过滤字段（brand_id, store_id, problem_type, tags, case_status）用于
    向量搜索时的结构化过滤，满足 Requirement 5.2。
    """

    __tablename__ = "case_vectors"

    vector_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, unique=True)
    case_updated_at = Column(DateTime(timezone=True), nullable=False)
    enrichment_id = Column(String(64), nullable=True)
    enrichment_status = Column(String(32), nullable=True)
    embedding_model_id = Column(String(128), nullable=False)
    embedding_dimension = Column(Integer, nullable=False)
    embedding_vector = Column(Vector(1024), nullable=False)
    brand_id = Column(String(64), nullable=False)
    store_id = Column(String(64), nullable=False)
    problem_type = Column(String(64), nullable=False)
    tags = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    case_status = Column(String(32), nullable=False)
    degraded_reason = Column(String(256), nullable=True)

    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_vectors_case_id"),
        Index("ix_case_vectors_brand_id", "brand_id"),
        Index("ix_case_vectors_store_id", "store_id"),
        Index("ix_case_vectors_problem_type", "problem_type"),
        Index("ix_case_vectors_case_status", "case_status"),
        Index("ix_case_vectors_case_updated_at", "case_updated_at"),
        # HNSW index for semantic search with cosine similarity
        Index(
            "ix_case_vectors_embedding_hnsw",
            "embedding_vector",
            postgresql_using="hnsw",
            postgresql_ops={"embedding_vector": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 200},
        ),
        # GIN index for JSONB tags filtering
        Index(
            "ix_case_vectors_tags_gin",
            "tags",
            postgresql_using="gin",
        ),
    )


class VectorIndexJob(Base):
    """向量索引任务记录表。

    存储向量索引任务的生命周期、来源版本、错误阶段和重试元数据。
    包含审计字段（old_vector_id、old_content_hash、new_vector_id）用于追溯。
    不存储完整的输入文本或向量数组。
    """

    __tablename__ = "vector_index_jobs"

    job_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    job_type = Column(String(32), nullable=False)  # index/refresh/retry/remove
    status = Column(String(32), nullable=False, index=True)
    source_version = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    old_vector_id = Column(String(64), nullable=True)
    old_content_hash = Column(String(128), nullable=True)
    new_vector_id = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_stage = Column(String(32), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_vector_index_jobs_case_id_started", "case_id", "started_at"),
        Index("ix_vector_index_jobs_next_retry_at", "next_retry_at"),
    )