"""向量索引远程 embedding 适配：供应商隔离、响应校验与错误映射。"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import openai
from openai import AsyncOpenAI

from app.core.llm_client import LLMClientError, _normalize_openai_base_url
from app.core.config import EmbeddingConfig
from app.core.errors import ErrorCode
from app.vector_indexing.schemas import EmbeddingRequest, EmbeddingResult

logger = logging.getLogger(__name__)

_LOG_DETAIL_MAX = 900


def _truncate_detail(text: str, limit: int = _LOG_DETAIL_MAX) -> str:
    """截断冗长诊断串，避免日志撑爆。"""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _format_raw_openai_exception(exc: BaseException) -> str:
    """从 OpenAI SDK 异常提取可诊断摘要（不含请求正文或向量）。"""
    parts: list[str] = [type(exc).__name__]
    if isinstance(exc, openai.APIStatusError):
        parts.append(f"http={exc.status_code}")
        body = getattr(exc, "body", None)
        if body is not None:
            parts.append(f"body={_truncate_detail(str(body), 600)}")
    raw = str(exc).strip()
    if raw:
        parts.append(_truncate_detail(raw, 500))
    return " | ".join(parts)


def _diagnostic_tail(exc: BaseException, limit: int = 400) -> str:
    """人类可读的一小段异常摘要，写入 LLMClientError.message。"""
    s = str(exc).strip()
    if not s:
        return ""
    return f": {_truncate_detail(s, limit)}"


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
            message=f"Embedding 调用超时{_diagnostic_tail(exc)}",
            retryable=treat_as_transient_retryable,
            status_code=503,
        )
    if isinstance(exc, openai.RateLimitError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_RATE_LIMITED,
            message=f"Embedding 限流{_diagnostic_tail(exc)}",
            retryable=treat_as_transient_retryable,
            status_code=_dep_status(429),
        )
    if isinstance(exc, openai.APIConnectionError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message=f"Embedding 网关连接失败{_diagnostic_tail(exc)}",
            retryable=treat_as_transient_retryable,
            status_code=dep_http,
        )
    if isinstance(exc, openai.AuthenticationError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message=f"Embedding 网关鉴权失败{_diagnostic_tail(exc)}",
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
            message=f"Embedding 网关错误 HTTP {status_code}{_diagnostic_tail(exc)}",
            retryable=retryable,
            status_code=_dep_status(status_code),
        )
    if isinstance(exc, openai.OpenAIError):
        return LLMClientError(
            error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
            message=f"Embedding 网关错误{_diagnostic_tail(exc)}",
            retryable=treat_as_transient_retryable,
            status_code=dep_http,
        )
    return LLMClientError(
        error_code=ErrorCode.EMBEDDING_PROVIDER_ERROR,
        message=f"Embedding 未知错误{_diagnostic_tail(exc)}",
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

        ``AsyncOpenAI`` 采用懒创建：仅在实际调用 ``embed_for_*`` 时构造，
        避免只读状态类 API（如 ``GET /vector-index``）在依赖注入阶段被
        同步 DNS/httpx 初始化拖慢数秒。

        Args:
            config: 嵌入模型与索引/搜索路径超时配置。
            _async_client_index: 可选注入索引路径 ``AsyncOpenAI``（单测）。
            _async_client_search: 可选注入搜索路径 ``AsyncOpenAI``（单测）。
        """
        self._config = config
        self._model_id = config.model_id
        self._expected_dim = config.vector_dimension
        self._base_url = _normalize_openai_base_url(config.base_url)
        self._timeout_index_s = config.index_timeout_ms / 1000.0
        self._timeout_search_s = config.search_timeout_ms / 1000.0
        self._injected_index = _async_client_index
        self._injected_search = _async_client_search
        self._lazy_index: AsyncOpenAI | None = None
        self._lazy_search: AsyncOpenAI | None = None

    def _get_client_index(self) -> AsyncOpenAI:
        if self._injected_index is not None:
            return self._injected_index
        if self._lazy_index is None:
            self._lazy_index = AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._base_url,
                timeout=self._timeout_index_s,
            )
        return self._lazy_index

    def _get_client_search(self) -> AsyncOpenAI:
        if self._injected_search is not None:
            return self._injected_search
        if self._lazy_search is None:
            self._lazy_search = AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._base_url,
                timeout=self._timeout_search_s,
            )
        return self._lazy_search

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
            client=self._get_client_index(),
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
            client=self._get_client_search(),
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
        error_message: str | None = None,
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
        if error_message:
            extra["error_message"] = _truncate_detail(error_message, 1024)
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
                    error_message=exc.message,
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
            detail = _format_raw_openai_exception(exc)
            logger.warning(
                "向量索引 embedding 供应商原始异常: %s",
                detail,
                extra={
                    "embedding_model_id": self._model_id,
                    "case_id": request.case_id,
                    "correlation_id": request.correlation_id,
                    "content_fingerprint": request.content_fingerprint,
                    "search_path": search_path,
                },
            )
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
