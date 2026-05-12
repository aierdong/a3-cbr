"""RerankerClient：调用远程 reranker 并统一响应。

接入默认 model `qwen3-reranker-8b`（可配置 api_key/base_url），
通过共享 LLMClient 或独立 HTTP 客户端执行重排调用。

提交标准化查询和候选问题画像文档并接收每个候选的纯语义相关性分值。

统一处理超时、限流、供应商失败、配置缺失和不可解析响应。
成功响应返回可排序语义分值，失败响应返回稳定错误和耗时元数据。

Boundary: RerankerClient (uses RerankerConfig)
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm_client import LLMClientError, RerankerClient as SharedRerankerClient
from app.core.config import RerankerConfig
from app.core.errors import ErrorCode


logger = logging.getLogger(__name__)


# =============================================================================
# RerankerClient 专用异常（映射到 RETRIEVAL_RERANKER_* 错误码）
# =============================================================================


class RerankerClientError(Exception):
    """RerankerClient 基础异常。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_FAILED


class RerankerTimeout(RerankerClientError):
    """Reranker 调用超时。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_TIMEOUT


class RerankerRateLimited(RerankerClientError):
    """Reranker 限流。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_RATE_LIMITED


class RerankerProviderError(RerankerClientError):
    """Reranker 供应商故障。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_PROVIDER_ERROR


class RerankerInvalidResponse(RerankerClientError):
    """Reranker 响应无效。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_INVALID_RESPONSE


class RerankerConfigMissing(RerankerClientError):
    """Reranker 配置缺失（fail-closed）。"""

    error_code: str = ErrorCode.RETRIEVAL_RERANKER_CONFIG_MISSING


# =============================================================================
# RerankerClient 内部 Schema
# =============================================================================


class RerankResult(BaseModel):
    """Rerank 调用结果。"""

    scores: list[float] = Field(..., description="归一化语义分值列表（0..1）")
    model_id: str = Field(..., description="实际使用的模型标识")
    latency_ms: int = Field(..., description="调用耗时（毫秒）")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Feature Flag: 全局启用开关
# =============================================================================
# RED 阶段：flag 默认为 False，测试应跳过或失败
# GREEN 阶段：flag 改为 True，实现完成后移除 flag
RETRIEVAL_RERANKER_ENABLED = True


def is_reranker_enabled() -> bool:
    """检查 RerankerClient 功能是否启用。"""
    return RETRIEVAL_RERANKER_ENABLED


# =============================================================================
# RerankerClient
# =============================================================================


class RerankerClient:
    """远程 reranker 适配器。

    职责：
    1. 调用远程 reranker（默认 qwen3-reranker-8b）获取语义分值
    2. 分值归一化到 0..1
    3. 错误映射：timeout -> RerankerTimeout, rate_limit -> RerankerRateLimited,
       provider_error -> RerankerProviderError, invalid_response -> RerankerInvalidResponse
    4. 配置缺失时 fail-closed
    5. 记录调用耗时元数据

    使用共享 LLMClient 的 RerankerClient（位于 app.core.llm_client.py）。
    """

    def __init__(
        self,
        config: RerankerConfig,
        *,
        _async_client=None,
    ) -> None:
        """初始化 RerankerClient。

        Args:
            config: RerankerConfig 配置对象（由 llm-case-enrichment 定义）。
            _async_client: 可选注入 AsyncOpenAI（单测使用）。
        """
        self._config = config
        self._model_id = config.model_id
        self._timeout_ms = config.timeout_ms
        self._latency_ms: int | None = None

        # 使用共享的 RerankerClient（基于 AsyncOpenAI）
        self._client = SharedRerankerClient(
            config=config,
            _async_client=_async_client,
        )

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> RerankResult:
        """调用远程 reranker 并返回归一化语义分值。

        Args:
            query: 标准化查询文本。
            documents: 候选问题画像文档列表（与返回分值一一对应）。
            top_n: 可选，限制返回前 N 个结果。

        Returns:
            RerankResult：包含归一化分值、模型标识和调用耗时。

        Raises:
            RerankerTimeout: 调用超时。
            RerankerRateLimited: 限流。
            RerankerProviderError: 供应商失败。
            RerankerInvalidResponse: 响应无效。
            RerankerConfigMissing: 配置缺失。
        """
        # 配置缺失检查
        if not self._config.api_key:
            raise RerankerConfigMissing(
                "Reranker api_key 未配置，无法执行重排调用"
            )

        if not self._config.base_url:
            raise RerankerConfigMissing(
                "Reranker base_url 未配置，无法执行重排调用"
            )

        start_time = time.monotonic()
        try:
            # 调用共享 RerankerClient
            raw_scores = await self._client.rerank_scores(
                query=query,
                documents=list(documents),
                top_n=top_n,
            )
        except LLMClientError as exc:
            self._latency_ms = int((time.monotonic() - start_time) * 1000)
            raise self._map_llm_error(exc) from exc

        self._latency_ms = int((time.monotonic() - start_time) * 1000)

        # 归一化分值到 0..1
        normalized_scores = self._normalize_scores(raw_scores)

        return RerankResult(
            scores=normalized_scores,
            model_id=self._model_id,
            latency_ms=self._latency_ms,
        )

    @staticmethod
    def _normalize_scores(raw_scores: list[float]) -> list[float]:
        """将分值归一化到 0..1 范围。

        Args:
            raw_scores: 供应商原始分值列表。

        Returns:
            list[float]：归一化后的分值列表（每个值在 0..1 之间）。
        """
        if not raw_scores:
            return []

        # 裁剪到 0..1 范围
        return [max(0.0, min(1.0, float(score))) for score in raw_scores]

    @staticmethod
    def _map_llm_error(exc: LLMClientError) -> RerankerClientError:
        """将 LLMClientError 映射为 RerankerClient 专用异常。

        错误映射：
        - LLM_TIMEOUT -> RerankerTimeout
        - LLM_RATE_LIMITED -> RerankerRateLimited
        - LLM_PROVIDER_ERROR -> RerankerProviderError
        - LLM_INVALID_RESPONSE -> RerankerInvalidResponse
        - LLM_PRIVACY_CONFIG_MISSING -> RerankerConfigMissing
        - 其他 -> RerankerProviderError
        """
        error_code = exc.error_code

        if error_code == ErrorCode.LLM_TIMEOUT:
            return RerankerTimeout(str(exc))
        if error_code == ErrorCode.LLM_RATE_LIMITED:
            return RerankerRateLimited(str(exc))
        if error_code == ErrorCode.LLM_PROVIDER_ERROR:
            return RerankerProviderError(str(exc))
        if error_code == ErrorCode.LLM_INVALID_RESPONSE:
            return RerankerInvalidResponse(str(exc))
        if error_code == ErrorCode.LLM_PRIVACY_CONFIG_MISSING:
            return RerankerConfigMissing(str(exc))

        # 默认映射为 provider_error
        return RerankerProviderError(str(exc))

    @property
    def last_latency_ms(self) -> int | None:
        """返回最近一次调用的耗时（毫秒）。"""
        return self._latency_ms