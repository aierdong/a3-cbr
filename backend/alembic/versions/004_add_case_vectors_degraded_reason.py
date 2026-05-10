"""add degraded_reason to case_vectors

Revision ID: 004
Revises: 003
Create Date: 2026-05-10

记录降级索引路径原因（Req 1.4），对齐逻辑模型 CaseVectorRecord.degraded_reason。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 ``case_vectors`` 增加 ``degraded_reason`` 列。"""
    op.add_column(
        "case_vectors",
        sa.Column("degraded_reason", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    """移除 ``case_vectors.degraded_reason`` 列。"""
    op.drop_column("case_vectors", "degraded_reason")
