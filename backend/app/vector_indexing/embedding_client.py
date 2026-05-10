"""向量索引远程 embedding 适配：供应商隔离、响应校验与错误映射。"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import openai
from openai import AsyncOpenAI

from app.common.llm_client import LLMClientError, _normalize_openai_base_url
from app.core.config import EmbeddingConfig
from app.core.errors import ErrorCode
from app.vector_indexing.schemas import EmbeddingRequest, EmbeddingResult

logger = logging.getLogger(__name__)


def _map_openai_exception(
    exc: BaseException,
    *,
    treat_as_transient_retryable: bool,
    search_path: bool,
) -> LLMClientError:
    """OpenAI SDK 异常映射为向量索引稳定错误码。"""
    dep_http = 503 if search_path else None

    def _dep_status(raw: int | None) -> int | None:
        if search_path:
            return 503
        return raw

    if isinstance(exc, openai.APITimeoutError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_TIMEOUT,
            message="Embedding 调用超时",
            retryable=treat_as_transient_retryable,
            status_code=503,
        )
    if isinstance(exc, openai.RateLimitError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_RATE_LIMITED,
            message="Embedding 限流",
            retryable=treat_as_transient_retryable,
            status_code=_dep_status(429),
        )
    if isinstance(exc, openai.APIConnectionError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message="Embedding 网关连接失败",
            retryable=treat_as_transient_retryable,
            status_code=dep_http,
        )
    if isinstance(exc, openai.AuthenticationError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message="Embedding 网关鉴权失败",
            retryable=False,
            status_code=_dep_status(getattr(exc, "status_code", None)),
        )
    if isinstance(exc, openai.APIStatusError):
        status_code = exc.status_code
        transient = status_code >= 500 or status_code == 429
        retryable = transient and treat_as_transient_retryable
        code = (
            ErrorCode.EMBEDDING_RATE_LIMITED
            if status_code == 429
            else ErrorCode.EMBEDDING_PROVIDER_ERROR
        )
        return LLMClientError(
            error_code=code,
            message=f"Embedding 网关错误 HTTP {status_code}",
            retryable=retryable,
            status_code=_dep_status(status_code),
        )
    if isinstance(exc, openai.OpenAIError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message="Embedding 网关错误",
            retryable=treat_as_transient_retryable,
            status_code=dep_http,
        )
    return LLMClientError(
        error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
        message="Embedding 未知错误",
        retryable=False,
        status_code=dep_http,
    )


def _vectors_from_response(response: object, expected_n: int) -> list[list[float]]:
    rows = getattr(response, "data", None)
    if not rows or not isinstance(rows, list):
        raise LLMClientError(
            error_code=ErrorCode.EMBEDDING_INVALID_RESPONSE,
            message="Embedding 响应缺少 data",
            retryable=False,
            status_code=503,
        )
    try:
        sorted_rows = sorted(rows, key=lambda r: getattr(r, "index", 0))
    except (TypeError, AttributeError) as exc:
        raise LLMClientError(
            error_code=ErrorCode.EMBEDDING_INVALID_RESPONSE,
            message="Embedding 响应无法按 index 排序",
            retryable=False,
            status_code=503,
        ) from exc

    vectors: list[list[float]] = []
    for row in sorted_rows:
        emb = getattr(row, "embedding", None)
        if emb is None:
            raise LLMClientError(
                error_code=ErrorCode.EMBEDDING_INVALID_RESPONSE,
                message="Embedding 行缺少 embedding 字段",
                retryable=False,
                status_code=503,
            )
        vectors.append(list(emb))

    if len(vectors) != expected_n:
        raise LLMClientError(
            error_code=ErrorCode.EMBEDDING_INVALID_RESPONSE,
            message="Embedding 向量条数与输入不一致",
            retryable=False,
            status_code=503,
        )
    return vectors


def _validate_dimensions(
    vectors: list[list[float]],
    expected_dim: int,
) -> None:
    for vec in vectors:
        if len(vec) != expected_dim:
            raise LLMClientError(
                error_code=ErrorCode.EMBEDDING_DIMENSION_MISMATCH,
                message="Embedding 向量维度与配置不一致",
                retryable=False,
                status_code=503,
            )


class EmbeddingClient:
    """索引路径与搜索路径超时/重试分离的远程 Embedding 客户端。"""

    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        _async_client_index: AsyncOpenAI | None = None,
        _async_client_search: AsyncOpenAI | None = None,
    ) -> None:
        """初始化 EmbeddingClient。

        Args:
            config: 嵌入模型与索引/搜索路径超时配置。
            _async_client_index: 可选注入索引路径 ``AsyncOpenAI``（单测）。
            _async_client_search: 可选注入搜索路径 ``AsyncOpenAI``（单测）。
        """
        self._config = config
        self._model_id = config.model_id
        self._expected_dim = config.vector_dimension
        base_url = _normalize_openai_base_url(config.base_url)
        timeout_index = config.index_timeout_ms / 1000.0
        timeout_search = config.search_timeout_ms / 1000.0
        self._client_index = _async_client_index or AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=timeout_index,
        )
        self._client_search = _async_client_search or AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=timeout_search,
        )

    async def embed_for_index(self, request: EmbeddingRequest) -> EmbeddingResult:
        """索引刷新路径：使用 ``index_timeout_ms`` / ``index_max_retries``。

        Args:
            request: 包含待嵌入文本与日志标识。

        Returns:
            EmbeddingResult: 校验通过的向量结果。

        Raises:
            LLMClientError: 携带 ``EMBEDDING_*`` 稳定错误码。
        """
        return await self._embed_with_retries(
            request,
            client=self._client_index,
            max_retries=self._config.index_max_retries,
            treat_as_transient_retryable=True,
            task_kind="index",
            search_path=False,
        )

    async def embed_for_query(self, request: EmbeddingRequest) -> EmbeddingResult:
        """候选搜索路径：使用 ``search_timeout_ms``，不重试（503 语义）。

        Args:
            request: 包含查询文本与日志标识。

        Returns:
            EmbeddingResult: 校验通过的向量结果。

        Raises:
            LLMClientError: 携带 ``EMBEDDING_*`` 稳定错误码；语义上应对应服务不可用。
        """
        return await self._embed_with_retries(
            request,
            client=self._client_search,
            max_retries=self._config.search_max_retries,
            treat_as_transient_retryable=False,
            task_kind="search",
            search_path=True,
        )

    def _log(
        self,
        *,
        request: EmbeddingRequest,
        task_kind: Literal["index", "search"],
        status: str,
        attempt: int,
        error_code: str | None,
    ) -> None:
        extra = {
            "embedding_task_kind": task_kind,
            "embedding_model_id": self._model_id,
            "case_id": request.case_id,
            "correlation_id": request.correlation_id,
            "content_fingerprint": request.content_fingerprint,
            "status": status,
            "attempt": attempt,
        }
        if error_code:
            extra["error_code"] = error_code
        msg = "向量索引 embedding 调用"
        if status == "success":
            logger.info(msg, extra=extra)
        else:
            logger.warning(msg, extra=extra)

    async def _embed_with_retries(
        self,
        request: EmbeddingRequest,
        *,
        client: AsyncOpenAI,
        max_retries: int,
        treat_as_transient_retryable: bool,
        task_kind: Literal["index", "search"],
        search_path: bool,
    ) -> EmbeddingResult:
        last_error: LLMClientError | None = None
        for attempt in range(max_retries + 1):
            try:
                result = await self._embed_once(
                    request,
                    client=client,
                    treat_as_transient_retryable=treat_as_transient_retryable,
                    search_path=search_path,
                )
                self._log(
                    request=request,
                    task_kind=task_kind,
                    status="success",
                    attempt=attempt + 1,
                    error_code=None,
                )
                return result
            except LLMClientError as exc:
                last_error = exc
                self._log(
                    request=request,
                    task_kind=task_kind,
                    status="error",
                    attempt=attempt + 1,
                    error_code=exc.error_code,
                )
                if not exc.retryable or attempt >= max_retries:
                    raise
                delay = min(2**attempt, 8)
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def _embed_once(
        self,
        request: EmbeddingRequest,
        *,
        client: AsyncOpenAI,
        treat_as_transient_retryable: bool,
        search_path: bool,
    ) -> EmbeddingResult:
        try:
            response = await client.embeddings.create(
                model=self._model_id,
                input=[request.text],
            )
        except Exception as exc:
            raise _map_openai_exception(
                exc,
                treat_as_transient_retryable=treat_as_transient_retryable,
                search_path=search_path,
            ) from exc

        vectors = _vectors_from_response(response, expected_n=1)
        _validate_dimensions(vectors, self._expected_dim)
        return EmbeddingResult(
            embedding_model_id=self._model_id,
            embedding_dimension=len(vectors[0]),
            vector=vectors[0],
        )
