"""共享模型客户端基础设施。

提供 HTTP 调用、重试逻辑、超时处理和错误映射，
支持 EnrichmentLLMConfig 和 NormalizerLLMConfig 配置命名空间。
可被 llm-case-enrichment 和 cbr-retrieval-recommendation 规格共同使用。

使用官方 ``openai`` Python SDK（``AsyncOpenAI``，与 ``OpenAI`` 同属一包）
构造指向 OpenAI 兼容网关的请求：聊天补全、向量嵌入、rerank（``POST /rerank``）。
含指数退避重试（仅可重试错误）、超时与到 ``LLMClientError`` 的异常映射。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, Sequence, TypeVar, Union

import openai
from openai import AsyncOpenAI

from app.core.config import (
    EmbeddingConfig,
    EnrichmentLLMConfig,
    NormalizerLLMConfig,
    RerankerConfig,
)
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    LLMCompletionRequest,
    LLMCompletionResult,
    LLMTokenUsage,
)

logger = logging.getLogger(__name__)

_BASE_HAS_VER_SUFFIX = re.compile(r"/v\d+$", re.IGNORECASE)

T = TypeVar("T")


class LLMClientError(Exception):
    """模型网关客户端异常，携带结构化错误码。"""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        """初始化 LLMClientError。

        Args:
            error_code: 统一错误码（如 LLM_TIMEOUT）。
            message: 人类可读错误信息。
            retryable: 是否可重试。
            status_code: HTTP 状态码（可选）。
        """
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


def _normalize_openai_base_url(raw_base: str) -> str:
    """将配置的 ``base_url`` 规范为 OpenAI SDK 所需前缀（含 /v1、/v2 等）。
    deepseek 不需要 /v1
    """
    base = raw_base.rstrip("/")
    # if _BASE_HAS_VER_SUFFIX.search(base):
    #     return base
    # return f"{base}/v1"
    # deepseek 不需要 /v1
    return base


def _map_openai_exception(exc: BaseException) -> LLMClientError:
    """openai SDK 异常 -> LLMClientError（embedding/rerank/聊天共用错误码）。"""
    if isinstance(exc, openai.APITimeoutError):
        return LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message=f"模型网关超时: {exc}",
            retryable=True,
        )
    if isinstance(exc, openai.RateLimitError):
        return LLMClientError(
            error_code=ErrorCode.LLM_RATE_LIMITED,
            message="模型网关限流 (HTTP 429)",
            retryable=True,
            status_code=429,
        )
    if isinstance(exc, openai.APIConnectionError):
        return LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message=f"模型网关连接失败: {exc}",
            retryable=True,
        )
    if isinstance(exc, openai.AuthenticationError):
        return LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message=f"模型网关鉴权失败: {exc}",
            retryable=False,
            status_code=getattr(exc, "status_code", None),
        )
    if isinstance(exc, openai.APIStatusError):
        status_code = exc.status_code
        retryable = status_code >= 500 or status_code == 429
        code = (
            ErrorCode.LLM_RATE_LIMITED if status_code == 429 else ErrorCode.LLM_PROVIDER_ERROR
        )
        return LLMClientError(
            error_code=code,
            message=f"模型网关错误 (HTTP {status_code}): {exc}",
            retryable=retryable,
            status_code=status_code,
        )
    if isinstance(exc, openai.OpenAIError):
        return LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message=f"模型网关错误: {exc}",
            retryable=True,
        )
    return LLMClientError(
        error_code=ErrorCode.LLM_PROVIDER_ERROR,
        message=f"模型网关未知错误: {exc}",
        retryable=True,
    )


async def _execute_with_retries(
    max_retries: int,
    execute: Callable[[], Awaitable[T]],
    backoff_delay_fn: Callable[[int], float],
) -> T:
    """与历史 LLMClient 一致的重试语义。"""
    last_error: LLMClientError | None = None
    for attempt in range(max_retries + 1):
        try:
            return await execute()
        except LLMClientError as exc:
            last_error = exc
            if not exc.retryable:
                raise
            if attempt < max_retries:
                await asyncio.sleep(backoff_delay_fn(attempt))
    assert last_error is not None
    raise last_error


class LLMClient:
    """共享聊天补全客户端，基于 ``AsyncOpenAI`` 调用 OpenAI 兼容 ``/chat/completions``。

    支持：
    - 配置命名空间（EnrichmentLLMConfig / NormalizerLLMConfig）
    - 指数退避重试（仅对可重试错误）
    - 超时处理
    - 错误映射到统一错误码
    - 结构化日志（不记录完整 prompt 内容）
    """

    def __init__(
        self,
        config: Union[EnrichmentLLMConfig, NormalizerLLMConfig],
        *,
        _async_client: AsyncOpenAI | None = None,
    ) -> None:
        """初始化 LLMClient。

        Args:
            config: LLM 配置对象，支持 EnrichmentLLMConfig 或 NormalizerLLMConfig。
            _async_client: 可选注入 ``AsyncOpenAI``（单测使用）。
        """
        self._config = config
        self._api_key = config.api_key
        self._model_id = config.model_id
        self._openai_base_url = _normalize_openai_base_url(config.base_url)
        self._timeout_s = config.timeout_ms / 1000.0
        self._max_retries = config.max_retries
        self._client = _async_client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=self._openai_base_url,
            timeout=self._timeout_s,
        )

        self._privacy_acknowledged = getattr(
            config, "privacy_acknowledged", True,
        )

    async def complete_json(
        self,
        request: LLMCompletionRequest,
    ) -> LLMCompletionResult:
        """调用 LLM 并返回结构化结果。

        Args:
            request: LLM 调用请求，包含 prompt、model_id、task_type 等。

        Returns:
            LLMCompletionResult: 包含 content、model_id、usage、finish_reason。

        Raises:
            LLMClientError: 当调用失败且不可重试时抛出。
        """
        if not self._privacy_acknowledged:
            raise LLMClientError(
                error_code=ErrorCode.LLM_PRIVACY_CONFIG_MISSING,
                message="隐私配置未确认：privacy_acknowledged=False",
                retryable=False,
            )

        last_error: LLMClientError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                result = await self._do_request(request)
                self._log_call(
                    request, status="success", attempt=attempt + 1,
                )
                return result
            except LLMClientError as exc:
                last_error = exc
                self._log_call(
                    request,
                    status="error",
                    attempt=attempt + 1,
                    error_code=exc.error_code,
                )
                if not exc.retryable:
                    raise
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def _do_request(
        self,
        request: LLMCompletionRequest,
    ) -> LLMCompletionResult:
        """执行单次 SDK 调用。"""
        payload: dict = {
            "model": request.model_id,
            "messages": [
                {"role": "user", "content": request.prompt},
            ],
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        try:
            completion = await self._client.chat.completions.create(**payload)
        except LLMClientError:
            raise
        except Exception as exc:
            raise _map_openai_exception(exc) from exc

        return self._completion_result_from_sdk(completion, request.model_id)

    def _completion_result_from_sdk(
        self,
        completion: object,
        request_model_id: str,
    ) -> LLMCompletionResult:
        """从 SDK ``ChatCompletion`` 对象提取 ``LLMCompletionResult``。"""
        choices = getattr(completion, "choices", None)
        if not choices:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 响应缺少 choices",
                retryable=False,
            )

        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if content is None:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 响应 message 中缺少 content",
                retryable=False,
            )

        finish_reason = getattr(first_choice, "finish_reason", None)
        usage_data = getattr(completion, "usage", None)
        usage = None
        if usage_data is not None:
            try:
                usage = LLMTokenUsage(
                    prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
                )
            except Exception:
                usage = None

        actual_model = getattr(completion, "model", None) or request_model_id

        return LLMCompletionResult(
            content=content,
            model_id=actual_model,
            usage=usage,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """计算指数退避延迟（秒）。"""
        return min(2 ** attempt, 8)

    def _log_call(
        self,
        request: LLMCompletionRequest,
        *,
        status: str,
        attempt: int,
        error_code: str | None = None,
    ) -> None:
        """结构化日志：记录供应商、模型、任务类型、状态和错误类型。

        不记录完整 prompt 正文。
        """
        extra = {
            "api_key": self._api_key,
            "model_id": request.model_id,
            "task_type": request.task_type,
            "request_purpose": request.request_purpose,
            "status": status,
            "attempt": attempt,
        }
        if error_code:
            extra["error_code"] = error_code

        if status == "success":
            logger.info("LLM 调用成功", extra=extra)
        else:
            logger.warning("LLM 调用失败", extra=extra)


class EmbeddingClient:
    """向量嵌入客户端：``AsyncOpenAI.embeddings.create``（OpenAI 兼容 ``/embeddings``）。"""

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        _async_client: AsyncOpenAI | None = None,
    ) -> None:
        """初始化 EmbeddingClient。

        Args:
            config: 嵌入模型配置。
            _async_client: 可选注入 ``AsyncOpenAI``（单测使用）。
        """
        self._model_id = config.model_id
        self._timeout_s = config.timeout_ms / 1000.0
        self._max_retries = config.max_retries
        self._openai_base_url = _normalize_openai_base_url(config.base_url)
        self._client = _async_client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=self._openai_base_url,
            timeout=self._timeout_s,
        )

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """对文本批量生成嵌入向量；顺序与 ``texts`` 一致。"""
        if not texts:
            return []

        async def once() -> list[list[float]]:
            try:
                response = await self._client.embeddings.create(
                    model=self._model_id,
                    input=list(texts),
                )
            except Exception as exc:
                raise _map_openai_exception(exc) from exc
            return self._vectors_from_embedding_response(response, len(texts))

        return await _execute_with_retries(
            self._max_retries,
            once,
            backoff_delay_fn=lambda a: min(2 ** a, 8),
        )

    def _vectors_from_embedding_response(
        self,
        response: object,
        expected_n: int,
    ) -> list[list[float]]:
        rows = getattr(response, "data", None)
        if not rows or not isinstance(rows, list):
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="Embedding 响应缺少 data",
                retryable=False,
            )
        try:
            sorted_rows = sorted(rows, key=lambda r: getattr(r, "index", 0))
        except Exception as exc:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message=f"Embedding 响应无法按 index 排序: {exc}",
                retryable=False,
            ) from exc

        vectors: list[list[float]] = []
        for row in sorted_rows:
            emb = getattr(row, "embedding", None)
            if emb is None:
                raise LLMClientError(
                    error_code=ErrorCode.LLM_INVALID_RESPONSE,
                    message="Embedding 行缺少 embedding",
                    retryable=False,
                )
            vectors.append(list(emb))

        if len(vectors) != expected_n:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message=(
                    f"Embedding 向量条数与输入不一致: 期望 {expected_n}, 实际 {len(vectors)}"
                ),
                retryable=False,
            )
        return vectors


class RerankerClient:
    """远程 rerank：通过 ``AsyncOpenAI`` 的 ``post`` 调用 ``/rerank`` 扩展路径。

    兼容典型请求体：``model``、``query``、``documents``、可选 ``top_n``。
    解析 ``results`` 中的 ``index``与 ``relevance_score``，按原始 ``documents`` 顺序输出分值。
    """

    def __init__(
        self,
        config: RerankerConfig,
        *,
        _async_client: AsyncOpenAI | None = None,
    ) -> None:
        """初始化 RerankerClient。

        Args:
            config: Rerank 模型配置。
            _async_client: 可选注入 ``AsyncOpenAI``（单测使用）。
        """
        self._model_id = config.model_id
        self._timeout_s = config.timeout_ms / 1000.0
        self._max_retries = config.max_retries
        self._openai_base_url = _normalize_openai_base_url(config.base_url)
        self._client = _async_client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=self._openai_base_url,
            timeout=self._timeout_s,
        )

    async def rerank_scores(
        self,
        *,
        query: str,
        documents: Sequence[str],
        top_n: int | None = None,
    ) -> list[float]:
        """返回与 ``documents`` 同序的相关性分值列表。"""
        if not documents:
            return []

        async def once() -> list[float]:
            body: dict = {
                "model": self._model_id,
                "query": query,
                "documents": list(documents),
            }
            if top_n is not None:
                body["top_n"] = top_n
            try:
                data = await self._client.post(
                    "/rerank",
                    cast_to=dict,
                    body=body,
                )
            except Exception as exc:
                raise _map_openai_exception(exc) from exc
            if not isinstance(data, dict):
                raise LLMClientError(
                    error_code=ErrorCode.LLM_INVALID_RESPONSE,
                    message="Rerank 响应不是 JSON 对象",
                    retryable=False,
                )
            return self._scores_from_rerank_body(data, len(documents))

        return await _execute_with_retries(
            self._max_retries,
            once,
            backoff_delay_fn=lambda a: min(2 ** a, 8),
        )

    def _scores_from_rerank_body(self, data: dict, n: int) -> list[float]:
        results = data.get("results")
        if not isinstance(results, list):
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="Rerank 响应缺少 results 列表",
                retryable=False,
            )

        scores = [0.0] * n
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            raw_score = item.get("relevance_score")
            if not isinstance(idx, int) or not (0 <= idx < n):
                continue
            if not isinstance(raw_score, (int, float)):
                continue
            scores[idx] = float(raw_score)
            seen.add(idx)

        if len(seen) != n:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="Rerank 结果未能覆盖全部候选索引",
                retryable=False,
            )
        return scores
