"""基础测试模块。.

验证 FastAPI 应用可以启动并通过健康检查。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check():
    """验证健康检查端点返回正常状态。."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_app_created():
    """验证应用实例创建成功。."""
    assert app is not None
    assert app.title == "A3 案例管理系统"