"""Create case enrichment tables.

Revision ID: 002
Revises: 001
Create Date: 2026-05-09

创建案例增强派生结果表、运行记录表和推荐文案运行记录表。
- case_enrichment_results: 案例增强派生结果（每案例唯一），含摘要、结构化建议、标签和来源引用
- case_enrichment_runs: 案例增强运行记录，记录每次增强尝试的生命周期状态
- recommendation_copy_runs: 推荐文案 LLM 调用审计记录，仅记录调用审计、成本和 schema 校验结果
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 case_enrichment_results、case_enrichment_runs 和 recommendation_copy_runs 表及索引。"""
    # 创建 case_enrichment_results 表
    op.create_table(
        "case_enrichment_results",
        sa.Column("enrichment_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("case_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("problem_summary", sa.Text(), nullable=True),
        sa.Column("solution_summary", sa.Text(), nullable=True),
        sa.Column("structured_suggestions", sa.JSON(), nullable=False),
        sa.Column("tag_suggestions", sa.JSON(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("output_version", sa.String(32), nullable=False),
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
        sa.UniqueConstraint("case_id", name="uq_case_enrichment_results_case_id"),
    )

    # 创建 case_enrichment_results 索引
    op.create_index(
        "ix_case_enrichment_results_case_id",
        "case_enrichment_results",
        ["case_id"],
    )
    op.create_index(
        "ix_case_enrichment_results_case_id_status",
        "case_enrichment_results",
        ["case_id", "status"],
    )
    op.create_index(
        "ix_case_enrichment_results_case_id_updated",
        "case_enrichment_results",
        ["case_id", "case_updated_at"],
    )

    # 创建 case_enrichment_runs 表
    op.create_table(
        "case_enrichment_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("request_purpose", sa.String(128), nullable=False),
        sa.Column("case_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_stage", sa.String(32), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 创建 case_enrichment_runs 索引
    op.create_index(
        "ix_case_enrichment_runs_case_id",
        "case_enrichment_runs",
        ["case_id"],
    )
    op.create_index(
        "ix_case_enrichment_runs_status",
        "case_enrichment_runs",
        ["status"],
    )
    op.create_index(
        "ix_case_enrichment_runs_case_id_started",
        "case_enrichment_runs",
        [sa.text("case_id"), sa.text("started_at DESC")],
    )

    # 创建 recommendation_copy_runs 表
    op.create_table(
        "recommendation_copy_runs",
        sa.Column("copy_run_id", sa.String(64), primary_key=True),
        sa.Column("query_text_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("candidate_case_ids", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("request_purpose", sa.String(128), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("schema_validation_status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 创建 recommendation_copy_runs 索引
    op.create_index(
        "ix_recommendation_copy_runs_created_at",
        "recommendation_copy_runs",
        ["created_at"],
    )
    op.create_index(
        "ix_recommendation_copy_runs_status",
        "recommendation_copy_runs",
        ["status"],
    )


def downgrade() -> None:
    """删除 recommendation_copy_runs、case_enrichment_runs 和 case_enrichment_results 表及索引。"""
    # 删除 recommendation_copy_runs 索引
    op.drop_index(
        "ix_recommendation_copy_runs_status",
        table_name="recommendation_copy_runs",
    )
    op.drop_index(
        "ix_recommendation_copy_runs_created_at",
        table_name="recommendation_copy_runs",
    )

    # 删除 recommendation_copy_runs 表
    op.drop_table("recommendation_copy_runs")

    # 删除 case_enrichment_runs 索引
    op.drop_index(
        "ix_case_enrichment_runs_case_id_started",
        table_name="case_enrichment_runs",
    )
    op.drop_index(
        "ix_case_enrichment_runs_status",
        table_name="case_enrichment_runs",
    )
    op.drop_index(
        "ix_case_enrichment_runs_case_id",
        table_name="case_enrichment_runs",
    )

    # 删除 case_enrichment_runs 表
    op.drop_table("case_enrichment_runs")

    # 删除 case_enrichment_results 索引
    op.drop_index(
        "ix_case_enrichment_results_case_id_updated",
        table_name="case_enrichment_results",
    )
    op.drop_index(
        "ix_case_enrichment_results_case_id_status",
        table_name="case_enrichment_results",
    )
    op.drop_index(
        "ix_case_enrichment_results_case_id",
        table_name="case_enrichment_results",
    )

    # 删除 case_enrichment_results 表
    op.drop_table("case_enrichment_results")
