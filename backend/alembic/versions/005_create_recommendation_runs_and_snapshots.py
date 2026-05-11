"""Create recommendation runs and item snapshots tables.

Revision ID: 005
Revises: 004
Create Date: 2026-05-11

创建推荐运行记录表和推荐项快照表：
- recommendation_runs: 推荐运行记录，含 contract_version、reranker_status、聚合状态等
- recommendation_item_snapshots: 推荐项快照，含分值明细、排序位置和解释状态

设计约束：
- contract_version 在 create_run 时写入，fail_run/complete_run 不得改写
- reranker_status 列 NOT NULL，数据库默认 'pending'
- recommendation_item_id 不得等于字面 'RUN'（下游 recommendation-feedback 哨兵保留）
- final_score 默认 0.0，用于降级路径或未聚合候选
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 recommendation_runs 和 recommendation_item_snapshots 表及索引。"""
    # 创建 recommendation_runs 表
    op.create_table(
        "recommendation_runs",
        sa.Column("recommendation_run_id", sa.String(64), primary_key=True),
        sa.Column("query_text_hash", sa.String(128), nullable=False),
        sa.Column("applied_filters", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("score_weights", sa.JSON().with_variant(sa.JSON(), "postgresql"), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("requested_top_k", sa.Integer(), nullable=False),
        sa.Column("returned_count", sa.Integer(), nullable=False),
        sa.Column("vector_candidate_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("degraded_reason", sa.String(128), nullable=True),
        sa.Column("reranker_model_id", sa.String(128), nullable=False),
        sa.Column(
            "reranker_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("aggregation_status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # 创建 recommendation_runs 索引
    op.create_index(
        "ix_recommendation_runs_created_at",
        "recommendation_runs",
        ["created_at"],
    )
    op.create_index(
        "ix_recommendation_runs_status",
        "recommendation_runs",
        ["status"],
    )
    op.create_index(
        "ix_recommendation_runs_query_text_hash",
        "recommendation_runs",
        ["query_text_hash"],
    )

    # 创建 recommendation_item_snapshots 表
    op.create_table(
        "recommendation_item_snapshots",
        sa.Column("recommendation_item_id", sa.String(64), primary_key=True),
        sa.Column("recommendation_run_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("vector_id", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("vector_similarity_score", sa.Float(), nullable=False),
        sa.Column("semantic_similarity_score", sa.Float(), nullable=True),
        sa.Column("structured_similarity_score", sa.Float(), nullable=True),
        sa.Column("business_score", sa.Float(), nullable=True),
        sa.Column(
            "final_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "score_breakdown",
            sa.JSON().with_variant(sa.JSON(), "postgresql"),
            nullable=False,
        ),
        sa.Column("explanation_status", sa.String(32), nullable=False),
        sa.Column(
            "missing_fields",
            sa.JSON().with_variant(sa.JSON(), "postgresql"),
            nullable=False,
        ),
        sa.Column("case_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 创建 recommendation_item_snapshots 索引
    op.create_index(
        "ix_recommendation_item_snapshots_case_id",
        "recommendation_item_snapshots",
        ["case_id"],
    )
    op.create_index(
        "ix_recommendation_item_snapshots_run_rank",
        "recommendation_item_snapshots",
        ["recommendation_run_id", "rank"],
    )


def downgrade() -> None:
    """删除 recommendation_item_snapshots 和 recommendation_runs 表及索引。"""
    # 删除 recommendation_item_snapshots 索引
    op.drop_index(
        "ix_recommendation_item_snapshots_run_rank",
        table_name="recommendation_item_snapshots",
    )
    op.drop_index(
        "ix_recommendation_item_snapshots_case_id",
        table_name="recommendation_item_snapshots",
    )

    # 删除 recommendation_item_snapshots 表
    op.drop_table("recommendation_item_snapshots")

    # 删除 recommendation_runs 索引
    op.drop_index(
        "ix_recommendation_runs_query_text_hash",
        table_name="recommendation_runs",
    )
    op.drop_index(
        "ix_recommendation_runs_status",
        table_name="recommendation_runs",
    )
    op.drop_index(
        "ix_recommendation_runs_created_at",
        table_name="recommendation_runs",
    )

    # 删除 recommendation_runs 表
    op.drop_table("recommendation_runs")