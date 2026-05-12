"""悬空反馈记录清理（定时任务 + 管理端手动触发）。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feedback.models import RecommendationFeedback
from app.feedback.schemas import CleanupResult
from app.retrieval.models import RecommendationItemSnapshot, RecommendationRun


logger = logging.getLogger(__name__)


class FeedbackCleanupConfig(BaseModel):
    """反馈清理任务配置。"""

    enabled: bool = Field(default=True)
    interval_seconds: int = Field(default=3600, ge=1)
    batch_size: int = Field(default=1000, ge=1)


def load_feedback_cleanup_config(
    config_path: str = "config/cleanup.yaml",
) -> FeedbackCleanupConfig:
    """从 ``cleanup.yaml`` 读取 ``feedback_cleanup`` 段，缺失则用默认值。"""
    path = Path(config_path)
    if not path.exists():
        logger.warning("清理配置文件不存在: %s，反馈清理使用默认配置", config_path)
        return FeedbackCleanupConfig()

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        section = data.get("feedback_cleanup")
        if not isinstance(section, dict):
            logger.warning("cleanup.yaml 缺少 feedback_cleanup 段，使用默认配置")
            return FeedbackCleanupConfig()
        return FeedbackCleanupConfig(**section)
    except Exception:
        logger.exception("加载 feedback_cleanup 配置失败，使用默认配置")
        return FeedbackCleanupConfig()


async def cleanup_orphaned_feedback_once(session: AsyncSession) -> CleanupResult:
    """扫描并删除引用缺失运行或缺失推荐项快照的反馈记录。"""
    t0 = time.perf_counter()

    missing_run_stmt = (
        select(RecommendationFeedback.feedback_id)
        .outerjoin(
            RecommendationRun,
            RecommendationRun.recommendation_run_id
            == RecommendationFeedback.recommendation_run_id,
        )
        .where(RecommendationRun.recommendation_run_id.is_(None))
    )
    missing_item_stmt = (
        select(RecommendationFeedback.feedback_id)
        .where(RecommendationFeedback.recommendation_item_id.is_not(None))
        .outerjoin(
            RecommendationItemSnapshot,
            RecommendationItemSnapshot.recommendation_item_id
            == RecommendationFeedback.recommendation_item_id,
        )
        .where(RecommendationItemSnapshot.recommendation_item_id.is_(None))
    )

    r1 = await session.execute(missing_run_stmt)
    r2 = await session.execute(missing_item_stmt)
    ids = list(dict.fromkeys(list(r1.scalars().all()) + list(r2.scalars().all())))
    scanned_count = len(ids)

    deleted_count = 0
    if ids:
        del_stmt = delete(RecommendationFeedback).where(
            RecommendationFeedback.feedback_id.in_(ids),
        )
        result = await session.execute(del_stmt)
        await session.flush()
        deleted_count = int(result.rowcount or 0)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "feedback_cleanup orphan_scan scanned=%s deleted=%s duration_ms=%s",
        scanned_count,
        deleted_count,
        duration_ms,
    )

    return CleanupResult(
        success=True,
        scanned_count=scanned_count,
        deleted_count=deleted_count,
        duration_ms=duration_ms,
    )


class FeedbackCleanupBackgroundService:
    """按固定间隔执行 ``cleanup_orphaned_feedback_once``。"""

    def __init__(
        self,
        session_factory: Callable[..., AsyncSession],
        *,
        interval_seconds: int = 3600,
        enabled: bool = True,
    ) -> None:
        """初始化后台调度。

        Args:
            session_factory: 异步会话工厂（``async with factory() as session``）。
            interval_seconds: 周期间隔秒数。
            enabled: 为 ``False`` 时不启动 ``run_periodic``。
        """
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._enabled = enabled
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """注册后台任务。"""
        if not self._enabled:
            logger.info("反馈清理后台任务已禁用")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_periodic())

    async def stop(self) -> None:
        """停止后台循环。"""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_periodic(self) -> None:
        """周期调度入口。"""
        logger.info(
            "反馈清理后台任务启动 interval_seconds=%s",
            self._interval_seconds,
        )
        while not self._stop_event.is_set():
            try:
                async with self._session_factory() as session:
                    await cleanup_orphaned_feedback_once(session)
                    await session.commit()
            except Exception:
                logger.exception("反馈清理周期执行失败，下一周期重试")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
                break
            except asyncio.TimeoutError:
                continue

        logger.info("反馈清理后台任务已退出")
