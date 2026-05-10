"""PgvectorChecks 前置检查测试（扩展、版本、索引、列维度）。

Task 5.2 / Boundary: PgvectorChecks
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.errors import ErrorCode
from app.vector_indexing.pgvector_checks import (
    PgvectorDimensionMismatchError,
    PgvectorExtensionMissingError,
    PgvectorIndexMissingError,
    PgvectorVersionTooLowError,
    assert_extension_present,
    assert_min_version,
    assert_required_indexes_present,
    assert_vector_dimension,
)


def _admin_sync_url() -> str:
    u = make_url(settings.database_url_sync)
    return u.set(database="postgres").render_as_string(hide_password=False)


def _ephemeral_db_name() -> str:
    return f"a3_vec_chk_{uuid.uuid4().hex[:16]}"


def _create_database(db_name: str) -> None:
    from sqlalchemy import create_engine

    eng = create_engine(_admin_sync_url(), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}" TEMPLATE template0'))
    eng.dispose()


def _drop_database(db_name: str) -> None:
    from sqlalchemy import create_engine

    eng = create_engine(_admin_sync_url(), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :d AND pid <> pg_backend_pid()
                """,
            ),
            {"d": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    eng.dispose()


def _async_url_for_database(db_name: str) -> str:
    u = make_url(settings.database_url)
    return u.set(database=db_name).render_as_string(hide_password=False)


@pytest.mark.asyncio
async def test_assert_extension_present_raises_when_extension_missing() -> None:
    """无 vector 扩展的数据库上应抛出 PgvectorExtensionMissingError。"""
    db_name = _ephemeral_db_name()
    _create_database(db_name)
    eng = create_async_engine(_async_url_for_database(db_name))
    try:
        factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            with pytest.raises(PgvectorExtensionMissingError) as ei:
                await assert_extension_present(session)
            assert ei.value.error_code == ErrorCode.VECTOR_PGVECTOR_UNAVAILABLE
    finally:
        await eng.dispose()
        _drop_database(db_name)


@pytest.mark.asyncio
async def test_assert_min_version_raises_when_below_required(db_session: AsyncSession) -> None:
    """要求版本高于已安装版本时应抛出 PgvectorVersionTooLowError。"""
    with pytest.raises(PgvectorVersionTooLowError) as ei:
        await assert_min_version(db_session, min_version="999.99.99")
    assert ei.value.found
    assert ei.value.required == "999.99.99"


@pytest.mark.asyncio
async def test_assert_required_indexes_present_raises_after_index_dropped(
    db_session: AsyncSession,
) -> None:
    """临时删除 HNSW 索引后应报告缺失。"""
    trans = await db_session.begin()
    await db_session.execute(text("DROP INDEX IF EXISTS ix_case_vectors_embedding_hnsw"))
    try:
        with pytest.raises(PgvectorIndexMissingError) as ei:
            await assert_required_indexes_present(db_session)
        assert "ix_case_vectors_embedding_hnsw" in ei.value.missing
    finally:
        await trans.rollback()


@pytest.mark.asyncio
async def test_assert_vector_dimension_raises_on_mismatch(db_session: AsyncSession) -> None:
    """期望维度与列定义不一致时应抛出 PgvectorDimensionMismatchError。"""
    with pytest.raises(PgvectorDimensionMismatchError) as ei:
        await assert_vector_dimension(db_session, expected=7)
    assert ei.value.expected == 7
    assert ei.value.found == 1024


@pytest.mark.asyncio
async def test_all_preflight_checks_happy_path(db_session: AsyncSession) -> None:
    """标准 schema 下四项前置检查均应通过。"""
    await assert_extension_present(db_session)
    raw_ver = await db_session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = :n"),
        {"n": "vector"},
    )
    assert raw_ver
    # 测试环境可能低于设计默认 0.8.2；此处验证「不低于所设下限则通过」且返回值与 pg_extension 一致
    ver = await assert_min_version(db_session, min_version="0.8.0")
    assert ver == str(raw_ver)
    await assert_required_indexes_present(db_session)
    await assert_vector_dimension(db_session, expected=1024)
