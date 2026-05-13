"""Database session module.

Provides database session lifecycle management.
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)

# 会话依赖中非 handler 阶段耗时 INFO 阈值（毫秒）：连接池等待或 commit 异常长时便于排查
_SESSION_SLOW_MS = 500.0

# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# 创建会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 声明 ORM 基类
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection: get database session.

    For request-level session management in FastAPI routes.
    """
    t_enter = time.perf_counter()
    async with async_session_maker() as session:
        pool_acquire_ms = (time.perf_counter() - t_enter) * 1000.0
        try:
            yield session
            t_commit = time.perf_counter()
            await session.commit()
            commit_ms = (time.perf_counter() - t_commit) * 1000.0
            msg = "get_db timings pool_acquire_ms=%.1f commit_ms=%.1f"
            args = (pool_acquire_ms, commit_ms)
            if (
                pool_acquire_ms >= _SESSION_SLOW_MS
                or commit_ms >= _SESSION_SLOW_MS
            ):
                logger.info(msg, *args)
            else:
                logger.debug(msg, *args)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager: get database session.

    For non-FastAPI contexts (e.g., test fixtures, migration scripts).
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()