"""pgvector 启动前检查（扩展、版本、索引、向量列维度）。

设计组件 PgvectorChecks：生产配置缺失或扩展不可用时 fail closed（Req 6.4）。
"""

from __future__ import annotations

import re
from typing import ClassVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode


class PgvectorPreflightError(Exception):
    """pgvector 前置检查失败基类。"""

    error_code: ClassVar[str] = ErrorCode.VECTOR_PGVECTOR_UNAVAILABLE

    def __init__(self, message: str) -> None:
        """初始化并保存错误消息。"""
        super().__init__(message)
        self.message = message


class PgvectorExtensionMissingError(PgvectorPreflightError):
    """vector 扩展未安装。"""


class PgvectorVersionTooLowError(PgvectorPreflightError):
    """vector 扩展版本低于要求。"""

    def __init__(self, *, found: str, required: str) -> None:
        """记录已安装版本与要求下限。"""
        super().__init__(f"pgvector version too low: found={found!r}, required>={required!r}")
        self.found = found
        self.required = required


class PgvectorIndexMissingError(PgvectorPreflightError):
    """case_vectors 上缺少设计要求的索引。"""

    def __init__(self, *, missing: list[str]) -> None:
        """记录缺失的索引名列表。"""
        super().__init__(f"missing required indexes on case_vectors: {missing}")
        self.missing = missing


class PgvectorDimensionMismatchError(PgvectorPreflightError):
    """embedding_vector 列维度与设计不一致。"""

    def __init__(self, *, found: int, expected: int) -> None:
        """记录列维度与期望值。"""
        super().__init__(f"embedding_vector dimension mismatch: found={found}, expected={expected}")
        self.found = found
        self.expected = expected


_REQUIRED_CASE_VECTORS_INDEXES: frozenset[str] = frozenset(
    {
        "ix_case_vectors_embedding_hnsw",
        "ix_case_vectors_brand_id",
        "ix_case_vectors_store_id",
        "ix_case_vectors_problem_type",
        "ix_case_vectors_case_status",
        "ix_case_vectors_case_updated_at",
        "ix_case_vectors_tags_gin",
    },
)


def _version_tuple(v: str) -> tuple[int, ...]:
    """将 '0.8.2' / '0.8.2-beta' 等解析为可比较的整数元组。"""
    parts: list[int] = []
    for tok in v.strip().split("."):
        digits = ""
        for ch in tok:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _version_lt(a: str, b: str) -> bool:
    return _version_tuple(a) < _version_tuple(b)


def _parse_vector_dim_from_format_type(ft: str) -> int:
    m = re.search(r"vector\s*\(\s*(\d+)\s*\)", ft, re.IGNORECASE)
    if not m:
        msg = f"cannot parse vector dimension from format_type: {ft!r}"
        raise PgvectorPreflightError(msg)
    return int(m.group(1))


async def assert_extension_present(session: AsyncSession) -> None:
    """确认已安装 `vector` 扩展。

    Args:
        session: 异步数据库会话。

    Returns:
        无；缺失扩展时抛出 PgvectorExtensionMissingError。
    """
    row = (
        await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = :n"),
            {"n": "vector"},
        )
    ).first()
    if row is None:
        raise PgvectorExtensionMissingError("pgvector extension 'vector' is not installed")


async def assert_min_version(session: AsyncSession, *, min_version: str = "0.8.2") -> str:
    """确认 pgvector 版本不低于给定下限。

    Args:
        session: 异步数据库会话。
        min_version: 最低可接受版本字符串（默认 0.8.2）。

    Returns:
        当前 `pg_extension.extversion` 字符串。

    Raises:
        PgvectorExtensionMissingError: 扩展不存在。
        PgvectorVersionTooLowError: 版本低于 min_version。
    """
    row = (
        await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = :n"),
            {"n": "vector"},
        )
    ).first()
    if row is None or row[0] is None:
        raise PgvectorExtensionMissingError("pgvector extension 'vector' is not installed")
    found = str(row[0])
    if _version_lt(found, min_version):
        raise PgvectorVersionTooLowError(found=found, required=min_version)
    return found


async def assert_required_indexes_present(session: AsyncSession) -> None:
    """确认 `case_vectors` 上存在设计要求的全部索引。

    Args:
        session: 异步数据库会话。

    Returns:
        无；缺失任一则抛出 PgvectorIndexMissingError。
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = ANY (current_schemas(true))
                  AND tablename = 'case_vectors'
                """,
            ),
        )
    ).all()
    present = {str(r[0]) for r in rows}
    missing = sorted(_REQUIRED_CASE_VECTORS_INDEXES - present)
    if missing:
        raise PgvectorIndexMissingError(missing=missing)


async def assert_vector_dimension(session: AsyncSession, *, expected: int = 1024) -> None:
    """确认 `case_vectors.embedding_vector` 列维度与期望值一致。

    Args:
        session: 异步数据库会话。
        expected: 设计维度（默认 1024）。

    Returns:
        无；不一致时抛出 PgvectorDimensionMismatchError。
    """
    row = (
        await session.execute(
            text(
                """
                SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) AS ft
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'case_vectors'
                  AND a.attname = 'embedding_vector'
                  AND NOT a.attisdropped
                  AND n.nspname = ANY (current_schemas(true))
                """,
            ),
        )
    ).first()
    if row is None or row[0] is None:
        raise PgvectorPreflightError("case_vectors.embedding_vector column not found")
    found = _parse_vector_dim_from_format_type(str(row[0]))
    if found != expected:
        raise PgvectorDimensionMismatchError(found=found, expected=expected)
