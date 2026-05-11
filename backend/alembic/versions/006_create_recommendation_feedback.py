"""Create recommendation_feedback table.

Revision ID: 006
Revises: 005
Create Date: 2026-05-11

创建推荐反馈表、查询索引与 PostgreSQL 15+ UNIQUE NULLS NOT DISTINCT 幂等约束。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 recommendation_feedback 表及约束。"""
    op.create_table(
        "recommendation_feedback",
        sa.Column("feedback_id", sa.String(64), primary_key=True),
        sa.Column("recommendation_run_id", sa.String(64), nullable=False),
        sa.Column("recommendation_item_id", sa.String(64), nullable=True),
        sa.Column("case_id", sa.String(64), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("source_channel", sa.String(32), nullable=False),
        sa.Column("usefulness", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
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
        ),
    )
    op.create_index(
        "ix_recommendation_feedback_run_id",
        "recommendation_feedback",
        ["recommendation_run_id"],
    )
    op.create_index(
        "ix_recommendation_feedback_item_id",
        "recommendation_feedback",
        ["recommendation_item_id"],
    )
    op.create_index(
        "ix_recommendation_feedback_case_id",
        "recommendation_feedback",
        ["case_id"],
    )
    op.create_index(
        "ix_recommendation_feedback_actor_id",
        "recommendation_feedback",
        ["actor_id"],
    )
    op.create_index(
        "ix_recommendation_feedback_created_at",
        "recommendation_feedback",
        ["created_at"],
    )
    op.create_index(
        "ix_recommendation_feedback_usefulness",
        "recommendation_feedback",
        ["usefulness"],
    )
    _uq = (
        "ALTER TABLE recommendation_feedback ADD CONSTRAINT unique_feedback_target "
        "UNIQUE NULLS NOT DISTINCT (actor_id, recommendation_run_id, recommendation_item_id)"
    )
    op.execute(sa.text(_uq))


def downgrade() -> None:
    """删除 recommendation_feedback 表及约束。"""
    op.drop_constraint(
        "unique_feedback_target",
        "recommendation_feedback",
        type_="unique",
    )
    op.drop_index(
        "ix_recommendation_feedback_usefulness",
        table_name="recommendation_feedback",
    )
    op.drop_index(
        "ix_recommendation_feedback_created_at",
        table_name="recommendation_feedback",
    )
    op.drop_index(
        "ix_recommendation_feedback_actor_id",
        table_name="recommendation_feedback",
    )
    op.drop_index(
        "ix_recommendation_feedback_case_id",
        table_name="recommendation_feedback",
    )
    op.drop_index(
        "ix_recommendation_feedback_item_id",
        table_name="recommendation_feedback",
    )
    op.drop_index(
        "ix_recommendation_feedback_run_id",
        table_name="recommendation_feedback",
    )
    op.drop_table("recommendation_feedback")
