"""测试配置文件。.

提供测试夹具和测试应用。
"""
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import Base
from app.main import app
from app.retrieval.router import get_recommendation_service


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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def mock_recommendation_service(db_session) -> MagicMock:
    """Mock RecommendationService fixture。

    创建完全 mocked 的 RecommendationService 实例，
    并通过 app.dependency_overrides 替换 get_recommendation_service 依赖，
    避免在测试环境中调用真实的 LLMClient、RerankerClient 等（需要 API keys）。

    注意：某些测试需要 patch() 来模拟特定行为（如 normalizer 失败），
    这些 patch 与 dependency_override 配合使用。
    """
    from app.retrieval.router import get_recommendation_service

    mock_service = MagicMock()
    mock_service.async_get_similar_cases = AsyncMock(return_value={
        "status": "success",
        "contract_version": "1.0.0",
        "items": [],
        "total": 0,
    })

    async def override_get_recommendation_service(session: AsyncSession):
        return mock_service

    app.dependency_overrides[get_recommendation_service] = override_get_recommendation_service

    yield mock_service

    # 清理 override
    if get_recommendation_service in app.dependency_overrides:
        del app.dependency_overrides[get_recommendation_service]


# 需要从 app.db.session 导入 get_db
from app.db.session import get_db  # noqa: E402, F401