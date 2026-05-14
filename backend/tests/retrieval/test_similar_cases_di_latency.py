"""验证 /similar-cases 慢请求分析：依赖注入分段日志与 stub override 墙钟对比。"""

from __future__ import annotations

import logging
import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.retrieval.router import get_recommendation_service
from app.retrieval.schemas import RecommendationResponse, RunStatus
from app.retrieval.service import CONTRACT_VERSION


def _has_safe_test_database_url() -> bool:
    """与 conftest 中破坏性 DDL 规则对齐的预检（仅用于 skip）。"""
    raw = (os.environ.get("TEST_DATABASE_URL") or "").strip() or settings.database_url
    try:
        url = make_url(raw)
    except Exception:
        return False
    database = (url.database or "").strip()
    driver = (url.drivername or "").lower()
    lowered = raw.lower()
    if "sqlite" in driver and ":memory:" in lowered:
        return True
    if database.endswith("_test"):
        return True
    return os.environ.get("I_ACCEPT_PYTEST_WILL_DROP_ALL_ORM_TABLES_HERE", "").strip() == "1"


@pytest_asyncio.fixture
async def asgi_client_for_di_tests(db_session):
    """仅覆盖 get_db，不覆盖 get_recommendation_service（用于对比 HTTP 耗时）。"""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()


def test_get_recommendation_service_emits_segment_timings(caplog) -> None:
    """直连依赖工厂应打出 timings_ms（无需真实 DB，会话仅被保存未在执行期使用）。"""
    router_logger = logging.getLogger("app.retrieval.router")
    router_logger.addHandler(caplog.handler)
    router_logger.setLevel(logging.DEBUG)
    try:
        session = MagicMock(spec=AsyncSession)
        svc = get_recommendation_service(session)
    finally:
        router_logger.removeHandler(caplog.handler)
    assert svc is not None
    assert any(
        "get_recommendation_service timings_ms" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.skipif(
    not _has_safe_test_database_url(),
    reason="需 TEST_DATABASE_URL 指向 *_test 库或内存 SQLite，见 tests/conftest 安全规则",
)
@pytest.mark.asyncio
async def test_stub_service_override_http_faster_than_full_di(
    asgi_client_for_di_tests,
    mock_external_apis,
) -> None:
    """同一 ASGI 应用下：先跑真实 DI + mock 外部 API，再 stub service，后者墙钟应更短。"""
    payload = {"query_text": "烤肉店上菜慢", "top_k": 5}
    default_response = RecommendationResponse(
        recommendation_run_id="bench-run",
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

    client = asgi_client_for_di_tests
    t0 = time.perf_counter()
    r_full = await client.post("/api/recommendations/similar-cases", json=payload)
    t_full_ms = (time.perf_counter() - t0) * 1000.0
    assert r_full.status_code == 200, r_full.text

    async def override_recommendation_service():
        m = MagicMock()
        m.recommend_similar_cases = AsyncMock(return_value=default_response)
        m.get_run = AsyncMock(return_value=None)
        return m

    app.dependency_overrides[get_recommendation_service] = override_recommendation_service
    try:
        t0 = time.perf_counter()
        r_stub = await client.post("/api/recommendations/similar-cases", json=payload)
        t_stub_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        del app.dependency_overrides[get_recommendation_service]

    assert r_stub.status_code == 200, r_stub.text
    assert t_stub_ms < t_full_ms, (
        f"预期 stub 跳过重型 DI 后更快: full={t_full_ms:.1f}ms stub={t_stub_ms:.1f}ms"
    )
