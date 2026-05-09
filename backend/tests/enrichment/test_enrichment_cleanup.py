"""EnrichmentCleanupService 测试。

测试孤立派生数据清理服务的生命周期管理和清理逻辑。
Requirements: 7.4
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enrichment.cleanup import (
    EnrichmentCleanupConfig,
    EnrichmentCleanupService,
    load_cleanup_config,
)


# ---------------------------------------------------------------------------
# EnrichmentCleanupConfig 测试
# ---------------------------------------------------------------------------


class TestEnrichmentCleanupConfig:
    """清理配置测试。"""

    def test_default_values(self):
        """验证默认配置值。"""
        config = EnrichmentCleanupConfig()
        assert config.enabled is True
        assert config.interval_seconds == 86400
        assert config.batch_size == 1000

    def test_custom_values(self):
        """验证自定义配置值。"""
        config = EnrichmentCleanupConfig(
            enabled=False,
            interval_seconds=3600,
            batch_size=500,
        )
        assert config.enabled is False
        assert config.interval_seconds == 3600
        assert config.batch_size == 500


class TestLoadCleanupConfig:
    """从 YAML 文件加载清理配置的测试。"""

    def test_load_from_yaml(self, tmp_path):
        """验证从 YAML 文件正确加载配置。"""
        yaml_content = """\
enrichment_cleanup:
  enabled: true
  interval_seconds: 43200
  batch_size: 500
"""
        config_file = tmp_path / "cleanup.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        config = load_cleanup_config(str(config_file))
        assert config.enabled is True
        assert config.interval_seconds == 43200
        assert config.batch_size == 500

    def test_load_missing_file_returns_defaults(self):
        """验证配置文件不存在时返回默认配置。"""
        config = load_cleanup_config("/nonexistent/path/cleanup.yaml")
        assert config.enabled is True
        assert config.interval_seconds == 86400
        assert config.batch_size == 1000

    def test_load_missing_section_returns_defaults(self, tmp_path):
        """验证配置文件缺少 enrichment_cleanup 段时返回默认配置。"""
        yaml_content = """\
other_section:
  key: value
"""
        config_file = tmp_path / "cleanup.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        config = load_cleanup_config(str(config_file))
        assert config.enabled is True
        assert config.interval_seconds == 86400
        assert config.batch_size == 1000


# ---------------------------------------------------------------------------
# EnrichmentCleanupService 测试
# ---------------------------------------------------------------------------


class TestEnrichmentCleanupService:
    """清理服务核心逻辑测试。"""

    def _make_service(
        self,
        config: EnrichmentCleanupConfig | None = None,
        orphaned_case_ids: list[str] | None = None,
    ) -> tuple[EnrichmentCleanupService, AsyncMock]:
        """创建测试用清理服务实例。

        Args:
            config: 清理配置，默认使用启用的配置。
            orphaned_case_ids: 孤立案例 ID 列表，用于模拟查询结果。

        Returns:
            (service, mock_session_factory) 元组。
        """
        if config is None:
            config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)

        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        # 模拟查询孤立 case_id 的结果
        if orphaned_case_ids is None:
            orphaned_case_ids = []

        def _create_query_result(ids: list[str]) -> MagicMock:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = ids
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            return mock_result

        def _create_delete_result(count: int) -> MagicMock:
            mock_result = MagicMock()
            mock_result.rowcount = count
            return mock_result

        query_result = _create_query_result(orphaned_case_ids)

        # 第一次 execute 是查询孤立记录，后续是删除操作
        if orphaned_case_ids:
            mock_session.execute.side_effect = [
                query_result,
                _create_delete_result(len(orphaned_case_ids)),  # 删除 results
                _create_delete_result(len(orphaned_case_ids)),  # 删除 runs
            ]
        else:
            mock_session.execute.return_value = query_result

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )
        return service, mock_session_factory

    @pytest.mark.asyncio
    async def test_cleanup_finds_and_deletes_orphaned_records(self):
        """验证清理逻辑找到并删除孤立记录。

        2 个孤立 case_id -> 删除 2 条 results + 2 条 runs = 4 条记录。
        """
        service, mock_factory = self._make_service(
            orphaned_case_ids=["case_orphan_1", "case_orphan_2"],
        )

        deleted_count = await service.cleanup_orphaned_enrichments()

        # 每个孤立 case_id 对应一条 result 和一条 run，共 4 条
        assert deleted_count == 4
        mock_session = mock_factory.return_value
        # 应该执行查询和删除操作
        assert mock_session.execute.call_count >= 2  # 查询 + 删除
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_no_orphans(self):
        """验证没有孤立记录时不做任何删除。"""
        service, mock_factory = self._make_service(orphaned_case_ids=[])

        deleted_count = await service.cleanup_orphaned_enrichments()

        assert deleted_count == 0
        mock_session = mock_factory.return_value
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_database_error(self):
        """验证清理失败时回滚并抛出异常（由 run_periodic 捕获处理）。"""
        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)
        mock_session.execute.side_effect = Exception("Database connection lost")

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        with pytest.raises(Exception, match="Database connection lost"):
            await service.cleanup_orphaned_enrichments()

        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_sets_event(self):
        """验证 stop() 方法设置停止事件。"""
        service, _ = self._make_service()

        assert not service._stop_event.is_set()
        await service.stop()
        assert service._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_run_periodic_respects_stop(self):
        """验证 run_periodic() 在收到停止信号后退出。"""
        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        service, _ = self._make_service(config=config, orphaned_case_ids=[])

        # 启动后立即停止
        async def stop_after_delay():
            await asyncio.sleep(0.05)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_delay())
        await service.run_periodic()
        await stop_task

        # 如果能正常返回，说明停止机制工作正常

    @pytest.mark.asyncio
    async def test_run_periodic_disabled_config(self):
        """验证配置禁用时 run_periodic 立即退出。"""
        config = EnrichmentCleanupConfig(enabled=False)
        service, _ = self._make_service(config=config)

        await service.run_periodic()
        # 如果能立即返回，说明配置禁用检查工作正常

    @pytest.mark.asyncio
    async def test_run_periodic_continues_after_cleanup_failure(self):
        """验证单次清理失败后服务继续运行不崩溃。"""
        call_count = 0

        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        async def failing_then_succeeding(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First call fails")
            # 第二次调用返回空结果
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            return mock_result

        mock_session.execute.side_effect = failing_then_succeeding

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        async def stop_after_first_cleanup():
            # 等待第一次清理完成（包括失败处理）
            while call_count < 1:
                await asyncio.sleep(0.01)
            # 给 run_periodic 进入等待状态的时间
            await asyncio.sleep(0.1)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_first_cleanup())
        await service.run_periodic()
        await stop_task

        # 第一次调用失败，服务应记录错误日志并继续
        assert call_count >= 1


# ---------------------------------------------------------------------------
# 应用启动/关闭钩子集成测试
# Task 5.5: 验证 @app.on_event("startup") 和 @app.on_event("shutdown")
# ---------------------------------------------------------------------------


class TestStartupHookIntegration:
    """验证 startup 钩子正确初始化并启动清理服务。"""

    @pytest.mark.asyncio
    async def test_startup_handler_creates_and_starts_service(self):
        """startup 钩子应创建 EnrichmentCleanupService 实例并调用 start()。"""
        from app.main import start_cleanup_service

        mock_service = MagicMock()
        mock_service.start = MagicMock()

        with (
            patch("app.main.load_cleanup_config") as mock_load_config,
            patch("app.main.EnrichmentCleanupService", return_value=mock_service),
            patch("app.main.async_session_maker"),
        ):
            mock_load_config.return_value = EnrichmentCleanupConfig(
                enabled=True, interval_seconds=1, batch_size=10
            )

            await start_cleanup_service()

            mock_load_config.assert_called_once()
            mock_service.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_failure_does_not_block_app(self, caplog):
        """startup 钩子初始化失败时不应阻塞应用启动。

        即使配置加载或服务创建抛出异常，应用也应继续启动。
        """
        from app.main import start_cleanup_service

        with (
            patch("app.main.load_cleanup_config", side_effect=Exception("Config load failed")),
            caplog.at_level(logging.ERROR),
        ):
            # 不应抛出异常——应用继续启动
            await start_cleanup_service()

            # 错误被记录
            assert "增强清理服务启动失败" in caplog.text


class TestShutdownHookIntegration:
    """验证 shutdown 钩子正确停止清理服务。"""

    @pytest.mark.asyncio
    async def test_shutdown_handler_calls_stop(self):
        """shutdown 钩子应调用 cleanup_service.stop()。"""
        from app.main import stop_cleanup_service

        mock_service = MagicMock()
        mock_service.stop = AsyncMock()

        with patch("app.main.cleanup_service", mock_service):
            await stop_cleanup_service()

            mock_service.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handler_safe_when_service_is_none(self):
        """shutdown 钩子在 cleanup_service 为 None 时不应抛出异常。"""
        import app.main as main_module

        original_service = main_module.cleanup_service
        try:
            main_module.cleanup_service = None
            # 不应抛出异常
            await main_module.stop_cleanup_service()
        finally:
            main_module.cleanup_service = original_service

    @pytest.mark.asyncio
    async def test_shutdown_handler_logs_stopped(self, caplog):
        """shutdown 钩子停止服务后应记录日志。"""
        from app.main import stop_cleanup_service

        mock_service = MagicMock()
        mock_service.stop = AsyncMock()

        with (
            patch("app.main.cleanup_service", mock_service),
            caplog.at_level(logging.INFO),
        ):
            await stop_cleanup_service()

            assert any("增强清理服务已停止" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 周期性执行测试
# Task 5.5: 验证 interval_seconds 配置和多周期执行
# ---------------------------------------------------------------------------


class TestPeriodicExecution:
    """验证清理任务的周期性执行和配置间隔。"""

    @pytest.mark.asyncio
    async def test_run_periodic_runs_cleanup_multiple_times(self):
        """run_periodic 应在 interval_seconds 间隔内多次执行清理。

        使用最小间隔 1 秒，等待约 2.5 秒以观察至少 2 次清理周期。
        """
        config = EnrichmentCleanupConfig(
            enabled=True, interval_seconds=1, batch_size=10
        )
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        cleanup_count = 0

        async def counting_execute(*args, **kwargs):
            nonlocal cleanup_count
            cleanup_count += 1
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            return mock_result

        mock_session.execute.side_effect = counting_execute

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        async def stop_after_delay():
            await asyncio.sleep(2.5)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_delay())
        await service.run_periodic()
        await stop_task

        # 应至少执行了 2 次清理（间隔 1s，等待 2.5s）
        assert cleanup_count >= 2, (
            f"期望至少执行 2 次清理，实际执行 {cleanup_count} 次"
        )

    @pytest.mark.asyncio
    async def test_run_periodic_retries_after_failure_on_next_period(self):
        """清理失败后下一个周期应自动重试（验证至少执行 2 次）。"""
        call_count = 0
        config = EnrichmentCleanupConfig(
            enabled=True, interval_seconds=1, batch_size=10
        )
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        async def always_failing(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception(f"Database error #{call_count}")

        mock_session.execute.side_effect = always_failing

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        async def stop_after_two_failures():
            while call_count < 2:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_two_failures())
        await service.run_periodic()
        await stop_task

        assert call_count >= 2, (
            f"期望失败后至少重试 2 次，实际执行 {call_count} 次"
        )

    @pytest.mark.asyncio
    async def test_run_periodic_respects_interval_seconds_config(self):
        """run_periodic 应使用配置的 interval_seconds 控制间隔。

        使用 interval_seconds=2 和较短等待时间，验证在间隔结束前不会过早执行第二次。
        """
        config = EnrichmentCleanupConfig(
            enabled=True, interval_seconds=2, batch_size=10
        )
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        cleanup_count = 0

        async def counting_execute(*args, **kwargs):
            nonlocal cleanup_count
            cleanup_count += 1
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            return mock_result

        mock_session.execute.side_effect = counting_execute

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        # 只等 0.5 秒，远小于 2 秒间隔
        async def stop_after_short_delay():
            await asyncio.sleep(0.5)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_short_delay())
        await service.run_periodic()
        await stop_task

        # 在 0.5 秒内应只执行 1 次清理（间隔 2 秒）
        assert cleanup_count == 1, (
            f"期望 2 秒间隔内仅执行 1 次清理，实际执行 {cleanup_count} 次"
        )


# ---------------------------------------------------------------------------
# 错误处理和日志测试
# Task 5.5: 验证失败时的错误处理和日志记录
# ---------------------------------------------------------------------------


class TestErrorHandlingAndLogging:
    """验证清理任务失败时的错误处理和日志记录。"""

    @pytest.mark.asyncio
    async def test_cleanup_failure_logs_error(self, caplog):
        """清理失败时应记录异常日志。"""
        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)
        mock_session.execute.side_effect = Exception("Connection refused")

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        async def stop_after_failure():
            await asyncio.sleep(0.2)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_failure())

        with caplog.at_level(logging.ERROR):
            await service.run_periodic()
            await stop_task

        assert any("清理任务执行失败" in record.message for record in caplog.records)

    @staticmethod
    def _make_service(
        config: EnrichmentCleanupConfig | None = None,
        orphaned_case_ids: list[str] | None = None,
    ) -> tuple[EnrichmentCleanupService, AsyncMock]:
        """创建测试用清理服务实例。"""
        if config is None:
            config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)

        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        if orphaned_case_ids is None:
            orphaned_case_ids = []

        def _create_query_result(ids: list[str]) -> MagicMock:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = ids
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            return mock_result

        query_result = _create_query_result(orphaned_case_ids)
        mock_session.execute.return_value = query_result

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )
        return service, mock_session_factory

    @pytest.mark.asyncio
    async def test_run_periodic_logs_startup_info(self, caplog):
        """run_periodic 启动时应记录配置信息。"""
        config = EnrichmentCleanupConfig(
            enabled=True, interval_seconds=3600, batch_size=500
        )
        service, _ = self._make_service(config=config, orphaned_case_ids=[])

        async def stop_immediately():
            await asyncio.sleep(0.05)
            await service.stop()

        stop_task = asyncio.create_task(stop_immediately())

        with caplog.at_level(logging.INFO):
            await service.run_periodic()
            await stop_task

        assert any(
            "清理服务启动" in record.message for record in caplog.records
        ), "启动时应记录清理服务启动日志"

    @pytest.mark.asyncio
    async def test_run_periodic_logs_stop_info(self, caplog):
        """run_periodic 停止时应记录停止信息。"""
        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        service, _ = self._make_service(config=config, orphaned_case_ids=[])

        async def stop_immediately():
            await asyncio.sleep(0.05)
            await service.stop()

        stop_task = asyncio.create_task(stop_immediately())

        with caplog.at_level(logging.INFO):
            await service.run_periodic()
            await stop_task

        assert any(
            "清理服务已停止" in record.message for record in caplog.records
        ), "停止时应记录清理服务已停止日志"

    @pytest.mark.asyncio
    async def test_cleanup_success_logs_orphan_count(self, caplog):
        """清理发现孤立数据时应记录数量。"""
        config = EnrichmentCleanupConfig(enabled=True, interval_seconds=1, batch_size=10)
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        # 模拟发现 3 个孤立 case_id
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = ["orphan_1", "orphan_2", "orphan_3"]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        service = EnrichmentCleanupService(
            db_session_factory=mock_session_factory,
            config=config,
        )

        async def stop_after_cleanup():
            await asyncio.sleep(0.2)
            await service.stop()

        stop_task = asyncio.create_task(stop_after_cleanup())

        with caplog.at_level(logging.INFO):
            await service.run_periodic()
            await stop_task

        assert any(
            "孤立 case_id" in record.message for record in caplog.records
        ), "发现孤立数据时应记录数量"

    @pytest.mark.asyncio
    async def test_disabled_service_logs_skip(self, caplog):
        """配置禁用时应记录跳过启动日志。"""
        config = EnrichmentCleanupConfig(enabled=False)
        service, _ = self._make_service(config=config)

        with caplog.at_level(logging.INFO):
            await service.run_periodic()

        assert any(
            "清理服务已禁用" in record.message for record in caplog.records
        ), "禁用时应记录跳过启动日志"
