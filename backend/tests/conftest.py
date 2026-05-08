"""测试配置文件。.

提供测试夹具和测试应用。
"""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.session import Base, async_session_maker, engine
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环 fixture（session 级别）。."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator:
    """数据库会话 fixture。.

    每个测试函数使用独立的数据库会话。
    """
    async with engine.begin() as conn:
        # 创建所有表（测试用）
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        yield session

    async with engine.begin() as conn:
        # 清理所有表
        await conn.run_sync(Base.metadata.drop_all)


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