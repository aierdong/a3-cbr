"""测试配置文件。.

提供测试夹具和测试应用。
"""
from typing import AsyncGenerator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import Base
from app.main import app


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator:
    """数据库会话 fixture。.

    每个测试函数使用独立的数据库引擎和会话，避免事件循环关闭问题。
    """
    # 为每个测试创建独立的引擎
    test_engine = create_async_engine(
        settings.database_url,
        echo=settings.app_debug,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # 创建所有表（pgvector：`case_vectors.embedding_vector` 依赖扩展）
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # 创建会话
    test_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with test_session_maker() as session:
        yield session

    # 清理所有表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # 关闭引擎
    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """测试客户端 fixture。.

    使用测试数据库会话。
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# 需要从 app.db.session 导入 get_db
from app.db.session import get_db  # noqa: E402, F401