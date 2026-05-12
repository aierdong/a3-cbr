"""孤立派生数据清理服务。

定期扫描并清理孤立的派生数据（case_id 在 a3_cases 中不存在的
派生结果和运行记录）。

与 docs/cascade-deletion-design.md §4.4 对齐。
Requirements: 7.4
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import A3Case
from app.enrichment.models import CaseEnrichmentResult, CaseEnrichmentRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


class EnrichmentCleanupConfig(BaseModel):
    """清理服务配置。

    使用 Pydantic BaseModel（与 LLM 配置模式一致），不使用 BaseSettings。
    """

    enabled: bool = Field(default=True, description="是否启用清理服务")
    interval_seconds: int = Field(
        default=86400,
        ge=1,
        description="清理间隔（秒），默认每日执行",
    )
    batch_size: int = Field(
        default=1000,
        ge=1,
        description="每批次删除的记录数上限",
    )


def load_cleanup_config(
    config_path: str = "config/cleanup.yaml",
) -> EnrichmentCleanupConfig:
    """从 YAML 文件加载清理配置。

    配置文件不存在或缺少 enrichment_cleanup 段时返回默认配置。

    Args:
        config_path: 配置文件路径。

    Returns:
        清理配置实例。
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning("清理配置文件不存在: %s，使用默认配置", config_path)
        return EnrichmentCleanupConfig()

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        section = data.get("enrichment_cleanup")
        if not isinstance(section, dict):
            logger.warning(
                "清理配置文件缺少 enrichment_cleanup 段，使用默认配置",
            )
            return EnrichmentCleanupConfig()

        return EnrichmentCleanupConfig(**section)
    except Exception:
        logger.warning("加载清理配置失败，使用默认配置", exc_info=True)
        return EnrichmentCleanupConfig()


# ---------------------------------------------------------------------------
# 清理服务
# ---------------------------------------------------------------------------


class EnrichmentCleanupService:
    """孤立派生数据清理服务。

    定期扫描 case_enrichment_results 和 case_enrichment_runs，
    删除 case_id 在 a3_cases 中不存在的孤立记录。

    生命周期：
    - run_periodic(): 使用 asyncio.create_task 启动后台任务
    - stop(): 优雅停止
    - 单次清理失败：记录错误日志，下一个周期自动重试
    """

    def __init__(
        self,
        db_session_factory: Callable[[], AsyncSession],
        config: EnrichmentCleanupConfig,
    ) -> None:
        """初始化清理服务。

        Args:
            db_session_factory: 异步数据库会话工厂，每次清理周期创建新会话。
            config: 清理配置。
        """
        self._session_factory = db_session_factory
        self._config = config
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def run_periodic(self) -> None:
        """周期性执行清理任务。

        使用 asyncio.create_task 启动此方法作为后台任务。
        配置 enabled=False 时立即退出。
        单次清理失败时记录错误日志，下一个周期自动重试。
        """
        if not self._config.enabled:
            logger.info("清理服务已禁用，跳过启动")
            return

        logger.info(
            "清理服务启动: interval=%ds, batch_size=%d",
            self._config.interval_seconds,
            self._config.batch_size,
        )

        while not self._stop_event.is_set():
            try:
                deleted = await self.cleanup_orphaned_enrichments()
                if deleted > 0:
                    logger.info("本轮清理完成: 删除 %d 条孤立记录", deleted)
            except Exception:
                logger.exception("清理任务执行失败，将在下一个周期重试")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.interval_seconds,
                )
                # stop_event 被设置，退出循环
                break
            except asyncio.TimeoutError:
                # 超时说明正常进入下一个清理周期
                continue

        logger.info("清理服务已停止")

    async def cleanup_orphaned_enrichments(self) -> int:
        """清理孤立的派生数据。

        查找 case_id 在 a3_cases 中不存在的 case_enrichment_results
        和 case_enrichment_runs 记录，批量删除。

        Returns:
            删除的记录总数。

        Raises:
            Exception: 数据库操作失败时抛出（由调用方处理）。
        """
        session: AsyncSession = self._session_factory()
        total_deleted = 0

        try:
            # 查找孤立的 case_id（LEFT JOIN a3_cases）
            orphaned_stmt = (
                select(CaseEnrichmentResult.case_id)
                .outerjoin(A3Case, CaseEnrichmentResult.case_id == A3Case.case_id)
                .where(A3Case.case_id.is_(None))
                .distinct()
            )
            result = await session.execute(orphaned_stmt)
            orphaned_case_ids: list[str] = list(result.scalars().all())

            if not orphaned_case_ids:
                await session.commit()
                return 0

            logger.info("发现 %d 个孤立 case_id，开始批量清理", len(orphaned_case_ids))

            # 按批次删除
            for i in range(0, len(orphaned_case_ids), self._config.batch_size):
                batch = orphaned_case_ids[i : i + self._config.batch_size]

                # 删除孤立的派生结果
                del_results = await session.execute(
                    delete(CaseEnrichmentResult).where(
                        CaseEnrichmentResult.case_id.in_(batch),
                    ),
                )
                total_deleted += del_results.rowcount

                # 删除孤立的运行记录
                del_runs = await session.execute(
                    delete(CaseEnrichmentRun).where(
                        CaseEnrichmentRun.case_id.in_(batch),
                    ),
                )
                total_deleted += del_runs.rowcount

            await session.commit()
        except Exception:
            await session.rollback()
            raise

        return total_deleted

    async def stop(self) -> None:
        """优雅停止清理服务。"""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("清理服务停止信号已发送")

    def start(self) -> None:
        """启动清理服务后台任务。"""
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_periodic())
