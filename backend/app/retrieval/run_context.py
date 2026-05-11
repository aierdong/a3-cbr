"""RecommendationRunContext：推荐运行上下文管理器。

职责：
1. 自动创建运行记录（__enter__）
2. 保证运行记录终态一致性（__exit__）
3. 提供 complete() 和 fail() 方法供主流程显式写入终态

设计约束：
- contract_version 在 create_run 时写入，fail_run/complete_run 不得改写
- __exit__ 中若 completed 未置位且存在未捕获异常，须尽力写入 fail_run
- 不抑制异常传播

Boundary: RecommendationRunContext_
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.retrieval.repository import RecommendationRepository
    from app.retrieval.schemas import (
        RecommendationErrorData,
        RecommendationRunCreate,
        RunResult,
    )


logger = logging.getLogger(__name__)


class RecommendationRunContext:
    """推荐运行上下文管理器。

    生命周期：
    1. __enter__: 调用 repository.create_run 创建运行记录，返回 run_id
    2. 主流程：通过 complete() 或 fail() 显式写入终态
    3. __exit__: 若 completed 未置位且有未捕获异常，尽力写入 fail_run
    """

    def __init__(
        self,
        repository: RecommendationRepository,
        run_create: RecommendationRunCreate,
    ) -> None:
        """初始化上下文管理器。

        Args:
            repository: 推荐仓储实例。
            run_create: 运行创建数据（包含 query_text_hash, applied_filters,
                       score_weights, contract_version, requested_top_k 等）。
        """
        self._repository = repository
        self._run_create = run_create
        self._run_id: Optional[str] = None
        self._completed = False

    @property
    def run_id(self) -> Optional[str]:
        """获取当前运行标识。"""
        return self._run_id

    @property
    def is_completed(self) -> bool:
        """检查是否已写入终态。"""
        return self._completed

    async def __aenter__(self) -> str:
        """创建运行记录。

        Returns:
            推荐的 recommendation_run_id。

        Raises:
            repository.create_run 可能抛出的异常会上抛。
        """
        record = await self._repository.create_run(self._run_create)
        self._run_id = record.recommendation_run_id
        logger.info(
            "推荐运行记录已创建",
            extra={"run_id": self._run_id},
        )
        return self._run_id

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """保证运行记录终态一致性。

        规则：
        - 若 completed=True（已通过 complete() 或 fail() 写入终态），不做任何操作
        - 若有未捕获异常（exc_type is not None）：
          - 尽力调用 repository.fail_run 写入失败终态
          - 持久化失败时仅记录 critical 日志，不抛出
        - 若正常退出但未写入终态，记录 warning 日志

        Args:
            exc_type: 异常类型（若无异常则为 None）
            exc_val: 异常值
            exc_tb: 异常回溯

        Returns:
            False - 不抑制异常，允许异常继续传播
        """
        if self._completed:
            # 已通过 complete() 或 fail() 写入终态，无需处理
            return False

        if exc_type is not None:
            # 有未捕获异常：尽力写入失败终态
            error_message = f"{exc_type.__name__}: {exc_val}"
            logger.error(
                "推荐流程异常终止，写入失败终态",
                extra={
                    "run_id": self._run_id,
                    "exception": error_message,
                },
            )

            if self._run_id is not None:
                try:
                    from app.retrieval.schemas import RecommendationErrorData

                    error_data = RecommendationErrorData(
                        error_code="INTERNAL_ERROR",
                        internal_reason=error_message,
                    )
                    await self._repository.fail_run(self._run_id, error_data)
                    self._completed = True
                    logger.info(
                        "失败终态已写入",
                        extra={"run_id": self._run_id},
                    )
                except Exception as persist_error:
                    # 持久化本身失败：记录但不再抛出
                    logger.critical(
                        f"Failed to persist run failure: {persist_error}",
                        extra={"run_id": self._run_id},
                    )
        else:
            # 正常退出但未写入终态：记录告警（设计问题，应有 complete/fail 调用）
            logger.warning(
                f"Run {self._run_id} exited without terminal state write",
                extra={"run_id": self._run_id},
            )

        # 不抑制异常
        return False

    async def complete(self, result: RunResult) -> None:
        """标记运行成功完成。

        Args:
            result: 运行完成结果数据。

        Raises:
            repository.complete_run 可能抛出的异常会上抛。
        """
        if self._run_id is None:
            raise RuntimeError("Cannot complete: run_id is not set (create_run not called)")

        if self._completed:
            logger.warning(
                f"Run {self._run_id} already completed, skipping duplicate complete()",
                extra={"run_id": self._run_id},
            )
            return

        await self._repository.complete_run(self._run_id, result)
        self._completed = True
        logger.info(
            "推荐运行已完成",
            extra={
                "run_id": self._run_id,
                "status": result.status,
                "returned_count": result.returned_count,
            },
        )

    async def fail(self, error: RecommendationErrorData) -> None:
        """标记运行失败。

        Args:
            error: 错误数据。

        Raises:
            repository.fail_run 可能抛出的异常会上抛。
        """
        if self._run_id is None:
            raise RuntimeError("Cannot fail: run_id is not set (create_run not called)")

        if self._completed:
            logger.warning(
                f"Run {self._run_id} already completed, skipping duplicate fail()",
                extra={"run_id": self._run_id},
            )
            return

        await self._repository.fail_run(self._run_id, error)
        self._completed = True
        logger.info(
            "推荐运行已标记失败",
            extra={
                "run_id": self._run_id,
                "error_code": error.error_code,
            },
        )