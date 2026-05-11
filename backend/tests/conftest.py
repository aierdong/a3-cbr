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
async def mock_external_apis():
    """Mock 外部 API 调用（LLM、Embedding、Reranker）。

    使用 patch 来 mock 外部 API 客户端，避免真实的 API 调用。
    这样可以让测试使用真实的 RecommendationService 逻辑，
    同时避免需要 API keys 和网络调用。
    """
    from unittest.mock import patch, AsyncMock
    from app.enrichment.schemas import LLMCompletionResult, LLMTokenUsage
    from app.vector_indexing.schemas import EmbeddingResult
    from app.retrieval.reranker_client import RerankResult

    # Mock LLMClient.complete_json (用于 QueryNormalizer)
    mock_llm_result = LLMCompletionResult(
        content='{"normalized_query_text": "门店客户投诉处理方法", "query_structured_suggestions": {"suggested_problem_type": "客户投诉", "suggested_root_cause_category": "服务态度", "suggested_applicable_scenes": ["零售"], "suggested_tags": ["投诉"]}}',
        model_id="deepseek-v4-flash",
        usage=LLMTokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        finish_reason="stop",
    )

    # Mock EmbeddingClient.embed_for_query (用于向量搜索)
    mock_embedding_result = EmbeddingResult(
        embedding_model_id="text-embedding-3-small",
        embedding_dimension=1024,
        vector=[0.1] * 1024,
    )

    # Mock RerankerClient.rerank (用于重排)
    mock_rerank_result = RerankResult(
        scores=[0.92, 0.85, 0.78],
        model_id="qwen3-reranker-8b",
        latency_ms=150,
    )

    with patch("app.common.llm_client.LLMClient.complete_json", new=AsyncMock(return_value=mock_llm_result)):
        with patch("app.vector_indexing.embedding_client.EmbeddingClient.embed_for_query", new=AsyncMock(return_value=mock_embedding_result)):
            with patch("app.retrieval.reranker_client.RerankerClient.rerank", new=AsyncMock(return_value=mock_rerank_result)):
                yield


@pytest_asyncio.fixture(scope="function")
async def mock_recommendation_service(db_session) -> MagicMock:
    """Mock RecommendationService fixture（已弃用）。

    注意：此 fixture 已不再推荐使用。
    对于集成测试，应该使用 mock_external_apis fixture 来 mock 外部 API，
    而让真实的 RecommendationService 逻辑运行。

    保留此 fixture 仅为向后兼容。
    """
    from app.retrieval.router import get_recommendation_service

    from app.retrieval.schemas import RecommendationResponse, RunStatus
    from app.retrieval.service import CONTRACT_VERSION

    mock_service = MagicMock()

    # 创建符合 schema 的默认响应
    default_response = RecommendationResponse(
        recommendation_run_id="test-run-id",
        contract_version=CONTRACT_VERSION,
        status=RunStatus.EMPTY,
        applied_filters={},
        score_weights={},
        query_metadata={},
        items=[],
        degraded_reason=None,
        error_code=None,
        message=None,
    )

    # Mock recommend_similar_cases 方法（router 调用的主方法）
    mock_service.recommend_similar_cases = AsyncMock(return_value=default_response)
    # Mock async_get_similar_cases 方法（如果有其他地方调用）
    mock_service.async_get_similar_cases = AsyncMock(return_value=default_response)
    # Mock get_run 方法
    mock_service.get_run = AsyncMock(return_value=None)

    async def override_get_recommendation_service():
        return mock_service

    app.dependency_overrides[get_recommendation_service] = override_get_recommendation_service

    yield mock_service

    # 清理 override
    if get_recommendation_service in app.dependency_overrides:
        del app.dependency_overrides[get_recommendation_service]


# 需要从 app.db.session 导入 get_db
from app.db.session import get_db  # noqa: E402, F401