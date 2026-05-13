"""测试配置文件。.

提供测试夹具和测试应用。

安全说明（重要）：
    ``db_session`` 会在 teardown 时对该库执行 ``metadata.drop_all()``。
    若连接串指向日常开发库（例如默认的 ``a3_cases``），一次 ``pytest`` 即可删光
    业务表；``alembic_version`` 不在 ORM metadata 中，往往会单独留下。
    因此仅允许在「明显为测试用途」的库上执行破坏性 DDL，见
    ``_resolve_destructive_test_database_url``。
"""
import asyncio
import os
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import Base
from app.main import app

# 加载全部 ORM，确保 Base.metadata 与 Alembic 建表范围一致（create_all / drop_all）
import app.db.base  # noqa: F401, E402

# 共享库上并发 create_all/drop_all 会触发 PostgreSQL pg_type 唯一约束冲突；序列化 DDL。
_db_schema_lock = asyncio.Lock()

_UNSAFE_DB_CONFIRM = "I_ACCEPT_PYTEST_WILL_DROP_ALL_ORM_TABLES_HERE"


def _resolve_destructive_test_database_url() -> str:
    """返回允许执行 create_all / drop_all 的数据库 URL。

    优先级：
        1. 环境变量 ``TEST_DATABASE_URL``（须仍通过安全规则，或配合显式免责变量）
        2. ``settings.database_url``（须通过安全规则）

    安全规则（满足其一即可）：
        - URL 中的数据库名以 ``_test`` 结尾（推荐：独立测试库如 ``a3_cases_test``）
        - 内存 SQLite（``sqlite`` + ``:memory:``）
        - 设置 ``I_ACCEPT_PYTEST_WILL_DROP_ALL_ORM_TABLES_HERE=1`` 且目标库名不在拒绝列表
          （仅用于本地确知风险的临时场景，勿用于共享/生产库）

    Raises:
        RuntimeError: 未通过校验时，避免误删开发库。
    """
    raw = (os.environ.get("TEST_DATABASE_URL") or "").strip() or settings.database_url
    try:
        url = make_url(raw)
    except Exception as exc:  # noqa: BLE001 — 给出可读错误
        raise RuntimeError(f"无法解析测试数据库 URL: {raw!r}") from exc

    database = (url.database or "").strip()
    driver = (url.drivername or "").lower()
    lowered = raw.lower()

    def _fail(msg: str) -> None:
        raise RuntimeError(
            msg
            + "\n\n处理方式：\n"
            "  1) 在 PostgreSQL 中创建仅用于测试的库（名称建议以 _test 结尾），"
            "并设置环境变量 TEST_DATABASE_URL=postgresql+asyncpg://.../你的库_test\n"
            "  2) 或将 .env 中 database_url 指向该测试库后再运行 pytest\n"
            "应用运行时不会自动执行迁移或 drop_all；危险操作仅来自本测试夹具。\n"
        )

    if "sqlite" in driver and ":memory:" in lowered:
        return raw

    if not database:
        _fail("测试数据库 URL 未包含数据库名（database），拒绝执行 drop_all。")

    if database.endswith("_test"):
        return raw

    unsafe_allowed = os.environ.get(_UNSAFE_DB_CONFIRM, "").strip() == "1"
    denied = {"postgres", "template0", "template1", "a3_cases"}
    if database in denied and not unsafe_allowed:
        _fail(
            f"拒绝在库 {database!r} 上执行 pytest 的 drop_all（该名常见于开发/系统库）。"
            "请改用名称以 _test 结尾的独立测试库。"
        )

    if unsafe_allowed:
        return raw

    _fail(
        f"拒绝在库 {database!r} 上执行 drop_all：库名须以 _test 结尾，或改用内存 SQLite。"
        f"\n若你完全清楚后果，可临时设置 {_UNSAFE_DB_CONFIRM}=1（强烈不推荐）。"
    )


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator:
    """数据库会话 fixture。.

    每个测试函数使用独立的数据库引擎和会话，避免事件循环关闭问题。
    """
    async with _db_schema_lock:
        test_db_url = _resolve_destructive_test_database_url()
        # 为每个测试创建独立的引擎
        test_engine = create_async_engine(
            test_db_url,
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

    with patch("app.core.llm_client.LLMClient.complete_json", new=AsyncMock(return_value=mock_llm_result)):
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