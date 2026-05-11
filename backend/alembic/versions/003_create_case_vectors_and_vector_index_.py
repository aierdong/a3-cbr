"""create case_vectors and vector_index_jobs tables

Revision ID: 003
Revises: 002
Create Date: 2026-05-10

创建向量索引所需的两张表和全部索引：
- case_vectors: 保存成功案例向量、过滤字段、来源版本和生命周期
- vector_index_jobs: 保存向量索引任务生命周期、审计字段和重试元数据

设计约束：
- 每个案例最多一条向量记录（case_id UNIQUE 约束）
- 使用 pgvector.sqlalchemy.Vector(dim) 类型定义 embedding_vector 列
- HNSW 索引使用 cosine 操作符，支持语义相似度搜索
- ef_search 通过连接初始化时 SET hnsw.ef_search 动态调整（配置项 PGVECTOR_HNSW_EF_SEARCH）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql  # 导入 pg 方言模块

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VECTOR_DIMENSION = 1024  # default for bge-large-zh


def upgrade() -> None:
    """创建向量索引扩展、表和索引。"""
    # 启用 pgvector 扩展（前提是服务端已安装扩展包）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 验证 pgvector 版本不低于 0.8.2
    # 注意：此检查假设扩展已安装；生产环境需确保镜像包含扩展包
    op.execute(
        """
        DO $$
        DECLARE
            ext_version TEXT;
        BEGIN
            SELECT extversion INTO ext_version FROM pg_extension WHERE extname = 'vector';
            IF ext_version IS NULL THEN
                RAISE EXCEPTION 'pgvector extension not found';
            END IF;
            -- 版本格式为 '0.8.2' 等，需要解析主版本号比较
            IF ext_version < '0.8.2' THEN
                RAISE EXCEPTION 'pgvector version must be >= 0.8.2, found: %', ext_version;
            END IF;
        END $$;
        """
    )

    # 创建 case_vectors 表
    op.create_table(
        "case_vectors",
        sa.Column("vector_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False, unique=True),
        sa.Column("case_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrichment_id", sa.String(64), nullable=True),
        sa.Column("enrichment_status", sa.String(32), nullable=True),
        sa.Column("embedding_model_id", sa.String(128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_vector", Vector(VECTOR_DIMENSION), nullable=False),
        sa.Column("brand_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("problem_type", sa.String(64), nullable=False),
        sa.Column("tags", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False),
        sa.Column("case_status", sa.String(32), nullable=False),
        sa.UniqueConstraint("case_id", name="uq_case_vectors_case_id"),
    )

    # 创建 case_vectors B-tree 索引
    op.create_index("ix_case_vectors_brand_id", "case_vectors", ["brand_id"])
    op.create_index("ix_case_vectors_store_id", "case_vectors", ["store_id"])
    op.create_index("ix_case_vectors_problem_type", "case_vectors", ["problem_type"])
    op.create_index("ix_case_vectors_case_status", "case_vectors", ["case_status"])
    op.create_index("ix_case_vectors_case_updated_at", "case_vectors", ["case_updated_at"])

    # 创建 case_vectors HNSW 向量索引（cosine 相似度）
    # m=16, ef_construction=200 为设计指定的固定参数
    op.execute(
        """
        CREATE INDEX ix_case_vectors_embedding_hnsw
        ON case_vectors
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 200)
        """
    )

    # 创建 case_vectors tags GIN 索引（JSONB 标签过滤）
    op.create_index(
        "ix_case_vectors_tags_gin",
        "case_vectors",
        ["tags"],
        postgresql_using="gin",
    )

    # 创建 vector_index_jobs 表
    op.create_table(
        "vector_index_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False, index=True),
        sa.Column("job_type", sa.String(32), nullable=False),  # index/refresh/retry/remove
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("source_version", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("old_vector_id", sa.String(64), nullable=True),
        sa.Column("old_content_hash", sa.String(128), nullable=True),
        sa.Column("new_vector_id", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_stage", sa.String(32), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 创建 vector_index_jobs 复合索引
    op.create_index(
        "ix_vector_index_jobs_case_id_started",
        "vector_index_jobs",
        ["case_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_vector_index_jobs_next_retry_at",
        "vector_index_jobs",
        ["next_retry_at"],
    )


def downgrade() -> None:
    """删除 vector_index_jobs 和 case_vectors 表及索引。"""
    # 删除 vector_index_jobs 索引
    op.drop_index("ix_vector_index_jobs_next_retry_at", table_name="vector_index_jobs")
    op.drop_index("ix_vector_index_jobs_case_id_started", table_name="vector_index_jobs")
    op.drop_index("ix_vector_index_jobs_case_id", table_name="vector_index_jobs")
    op.drop_index("ix_vector_index_jobs_status", table_name="vector_index_jobs")

    # 删除 vector_index_jobs 表
    op.drop_table("vector_index_jobs")

    # 删除 case_vectors 索引
    op.drop_index("ix_case_vectors_tags_gin", table_name="case_vectors")
    op.drop_index("ix_case_vectors_case_updated_at", table_name="case_vectors")
    op.drop_index("ix_case_vectors_case_status", table_name="case_vectors")
    op.drop_index("ix_case_vectors_problem_type", table_name="case_vectors")
    op.drop_index("ix_case_vectors_store_id", table_name="case_vectors")
    op.drop_index("ix_case_vectors_brand_id", table_name="case_vectors")
    op.execute("DROP INDEX IF EXISTS ix_case_vectors_embedding_hnsw")

    # 删除 case_vectors 表
    op.drop_table("case_vectors")

    # 注意：不删除 vector 扩展，因为其他表可能依赖它