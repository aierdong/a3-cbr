"""Create store_infos and a3_cases tables.

Revision ID: 001
Revises:
Create Date: 2026-05-08

创建门店信息只读镜像表和 A3 案例基础表。
- store_infos: 外部门店主数据的只读镜像，业务数据由外部同步写入
- a3_cases: A3 案例基础表，包含案例标识、A3 基础字段、状态、时间戳和门店信息关联
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 store_infos 和 a3_cases 表及索引。"""
    # 创建 store_infos 表
    op.create_table(
        "store_infos",
        sa.Column("store_id", sa.String(64), primary_key=True),
        sa.Column("store_name", sa.String(255), nullable=False),
        sa.Column("brand_id", sa.String(64), nullable=False),
        sa.Column("brand_name", sa.String(255), nullable=False),
        sa.Column("business_type", sa.String(64), nullable=False),
        sa.Column("store_scale", sa.String(64), nullable=False),
        sa.Column("franchise_type", sa.String(32), nullable=False),
        sa.Column("city", sa.String(128), nullable=False),
        sa.Column("city_tier", sa.String(32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 创建 store_infos 索引
    op.create_index("ix_store_infos_brand_id", "store_infos", ["brand_id"])
    op.create_index("ix_store_infos_business_type", "store_infos", ["business_type"])
    op.create_index("ix_store_infos_store_scale", "store_infos", ["store_scale"])
    op.create_index("ix_store_infos_franchise_type", "store_infos", ["franchise_type"])
    op.create_index("ix_store_infos_city", "store_infos", ["city"])
    op.create_index("ix_store_infos_city_tier", "store_infos", ["city_tier"])

    # 创建 a3_cases 表
    op.create_table(
        "a3_cases",
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column("problem_description", sa.Text(), nullable=False),
        sa.Column(
            "store_id",
            sa.String(64),
            sa.ForeignKey("store_infos.store_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("problem_type", sa.String(64), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),  # JSONB stored as text
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("solution_steps", sa.Text(), nullable=False),  # JSONB stored as text
        sa.Column("outcome", sa.Text(), nullable=False),  # JSONB stored as text
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
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

    # 创建 a3_cases 索引
    op.create_index("ix_a3_cases_store_id", "a3_cases", ["store_id"])
    op.create_index("ix_a3_cases_problem_type", "a3_cases", ["problem_type"])
    op.create_index("ix_a3_cases_status", "a3_cases", ["status"])
    op.create_index("ix_a3_cases_created_at", "a3_cases", ["created_at"])
    op.create_index("ix_a3_cases_created_at_case_id", "a3_cases", ["created_at", "case_id"])


def downgrade() -> None:
    """删除 a3_cases 和 store_infos 表及索引。"""
    # 删除 a3_cases 索引
    op.drop_index("ix_a3_cases_created_at_case_id", table_name="a3_cases")
    op.drop_index("ix_a3_cases_created_at", table_name="a3_cases")
    op.drop_index("ix_a3_cases_status", table_name="a3_cases")
    op.drop_index("ix_a3_cases_problem_type", table_name="a3_cases")
    op.drop_index("ix_a3_cases_store_id", table_name="a3_cases")

    # 删除 a3_cases 表
    op.drop_table("a3_cases")

    # 删除 store_infos 索引
    op.drop_index("ix_store_infos_city_tier", table_name="store_infos")
    op.drop_index("ix_store_infos_city", table_name="store_infos")
    op.drop_index("ix_store_infos_franchise_type", table_name="store_infos")
    op.drop_index("ix_store_infos_store_scale", table_name="store_infos")
    op.drop_index("ix_store_infos_business_type", table_name="store_infos")
    op.drop_index("ix_store_infos_brand_id", table_name="store_infos")

    # 删除 store_infos 表
    op.drop_table("store_infos")
