"""共享 LLM 客户端基础设施。

提供 HTTP 调用、重试逻辑、超时处理和错误映射，
支持 EnrichmentLLMConfig 和 NormalizerLLMConfig 配置命名空间。
可被 llm-case-enrichment 和 cbr-retrieval-recommendation 规格共同使用。
"""
import asyncio
import logging
from typing import Union

import httpx

from app.core.config import EnrichmentLLMConfig, NormalizerLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    LLMCompletionRequest,
    LLMCompletionResult,
    LLMTokenUsage,
)

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """LLM 客户端异常，携带结构化错误码。"""

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


class LLMClient:
    """共享 LLM 客户端，封装 OpenAI 兼容 API 的 HTTP 调用。

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
    ) -> None:
        """初始化 LLMClient。

        Args:
            config: LLM 配置对象，支持 EnrichmentLLMConfig 或 NormalizerLLMConfig。
        """
        self._config = config
        self._provider = config.provider
        self._model_id = config.model_id
        self._base_url = config.base_url.rstrip("/")
        self._timeout_s = config.timeout_ms / 1000.0
        self._max_retries = config.max_retries

        # 隐私配置检查（仅 EnrichmentLLMConfig 有此字段）
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
        # 隐私配置校验
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

        # 所有重试耗尽
        assert last_error is not None
        raise last_error

    async def _do_request(
        self,
        request: LLMCompletionRequest,
    ) -> LLMCompletionResult:
        """执行单次 HTTP 请求。"""
        url = f"{self._base_url}/v1/chat/completions"
        payload = self._build_payload(request)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=self._timeout_s,
                )
            except httpx.TimeoutException as exc:
                raise LLMClientError(
                    error_code=ErrorCode.LLM_TIMEOUT,
                    message=f"LLM 调用超时 ({self._timeout_s}s)",
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMClientError(
                    error_code=ErrorCode.LLM_PROVIDER_ERROR,
                    message=f"HTTP 请求失败: {exc}",
                    retryable=True,
                ) from exc

        return self._handle_response(response, request.model_id)

    def _build_payload(self, request: LLMCompletionRequest) -> dict:
        """构造 OpenAI 兼容 API 请求体。"""
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
        return payload

    def _handle_response(
        self,
        response: httpx.Response,
        request_model_id: str,
    ) -> LLMCompletionResult:
        """映射 HTTP 响应到 LLMCompletionResult 或 LLMClientError。"""
        status = response.status_code

        if status == 429:
            raise LLMClientError(
                error_code=ErrorCode.LLM_RATE_LIMITED,
                message="LLM 供应商限流 (HTTP 429)",
                retryable=True,
                status_code=429,
            )

        if status >= 500:
            raise LLMClientError(
                error_code=ErrorCode.LLM_PROVIDER_ERROR,
                message=f"LLM 供应商故障 (HTTP {status})",
                retryable=True,
                status_code=status,
            )

        if status >= 400:
            raise LLMClientError(
                error_code=ErrorCode.LLM_PROVIDER_ERROR,
                message=f"LLM 请求错误 (HTTP {status}): {response.text[:200]}",
                retryable=False,
                status_code=status,
            )

        # 解析 JSON 响应
        try:
            data = response.json()
        except (ValueError, KeyError) as exc:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 响应无法解析为 JSON",
                retryable=False,
            ) from exc

        return self._parse_completion(data, request_model_id)

    def _parse_completion(
        self,
        data: dict,
        request_model_id: str,
    ) -> LLMCompletionResult:
        """从 OpenAI 兼容响应中提取结果。"""
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 响应缺少 choices 字段",
                retryable=False,
            )

        first_choice = choices[0]
        message = first_choice.get("message", {})
        content = message.get("content")
        if content is None:
            raise LLMClientError(
                error_code=ErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 响应 message 中缺少 content 字段",
                retryable=False,
            )

        finish_reason = first_choice.get("finish_reason")

        # 解析 usage（可选）
        usage_data = data.get("usage")
        usage = None
        if usage_data and isinstance(usage_data, dict):
            try:
                usage = LLMTokenUsage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )
            except Exception:
                usage = None

        # 优先使用响应中的 model，否则使用请求中的 model_id
        actual_model = data.get("model", request_model_id)

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
            "provider": self._provider,
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
