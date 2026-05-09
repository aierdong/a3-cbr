"""应用入口集成测试。

验证增强模块在应用入口中的集成：
- ORM metadata 包含增强表
- 清理服务在 startup 时注册
- 清理服务在 shutdown 时优雅停止

Requirements: 4.2, 4.3, 4.4, 6.3, 7.4
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.session import Base


class TestEnrichmentMetadata:
    """验证增强 ORM 模型已注册到 Base.metadata。"""

    def test_enrichment_tables_in_metadata(self):
        """Base.metadata 应包含增强相关的三张表。"""
        table_names = set(Base.metadata.tables.keys())
        assert "case_enrichment_results" in table_names, (
            "case_enrichment_results 未在 Base.metadata 中找到"
        )
        assert "case_enrichment_runs" in table_names, (
            "case_enrichment_runs 未在 Base.metadata 中找到"
        )
        assert "recommendation_copy_runs" in table_names, (
            "recommendation_copy_runs 未在 Base.metadata 中找到"
        )


class TestCleanupServiceLifecycle:
    """验证清理服务在应用启动/关闭时的生命周期。"""

    @pytest.mark.asyncio
    async def test_startup_registers_cleanup_service(self):
        """应用 startup 事件应启动清理服务后台任务。"""
        from app.main import app

        # 收集 startup 事件处理器
        startup_handlers = app.router.on_startup
        assert len(startup_handlers) > 0, "没有注册 startup 事件处理器"

        # 查找包含 cleanup 关键字的处理器
        cleanup_startup = None
        for handler in startup_handlers:
            if "cleanup" in handler.__name__ or hasattr(handler, "_is_cleanup"):
                cleanup_startup = handler
                break

        # 如果没有明确标记，检查是否存在 startup 处理器
        # （通过检查函数名或闭包引用）
        assert cleanup_startup is not None or any(
            "cleanup" in str(h) for h in startup_handlers
        ), "未找到清理服务的 startup 处理器"

    @pytest.mark.asyncio
    async def test_shutdown_stops_cleanup_service(self):
        """应用 shutdown 事件应停止清理服务。"""
        from app.main import app

        shutdown_handlers = app.router.on_shutdown
        assert len(shutdown_handlers) > 0, "没有注册 shutdown 事件处理器"

        # 查找包含 cleanup 关键字的处理器
        cleanup_shutdown = any(
            "cleanup" in str(h) for h in shutdown_handlers
        )
        assert cleanup_shutdown, "未找到清理服务的 shutdown 处理器"

    @pytest.mark.asyncio
    async def test_cleanup_service_stop_called_on_shutdown(self):
        """shutdown 事件应调用 cleanup_service.stop()。"""
        from app.main import app

        # 模拟 cleanup_service
        mock_cleanup = MagicMock()
        mock_cleanup.stop = AsyncMock()
        mock_cleanup.run_periodic = AsyncMock()

        with patch("app.main.cleanup_service", mock_cleanup):
            # 触发 shutdown 事件
            for handler in app.router.on_shutdown:
                if "cleanup" in str(handler):
                    await handler()
                    break

            mock_cleanup.stop.assert_called_once()
