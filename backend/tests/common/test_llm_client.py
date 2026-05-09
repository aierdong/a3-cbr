"""LLMClient 单元测试。

覆盖：成功调用、超时、限流、供应商错误、无效响应、隐私校验、重试逻辑。
"""
import pytest
import httpx

from app.common.llm_client import LLMClient, LLMClientError
from app.core.config import EnrichmentLLMConfig, NormalizerLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    LLMCompletionRequest,
    RequestPurpose,
    TaskType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _enrichment_config(**overrides) -> EnrichmentLLMConfig:
    defaults = {
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "timeout_ms": 10000,
        "max_retries": 2,
        "privacy_acknowledged": True,
    }
    defaults.update(overrides)
    return EnrichmentLLMConfig(**defaults)


def _normalizer_config(**overrides) -> NormalizerLLMConfig:
    defaults = {
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "timeout_ms": 10000,
        "max_retries": 2,
    }
    defaults.update(overrides)
    return NormalizerLLMConfig(**defaults)


def _completion_request(**overrides) -> LLMCompletionRequest:
    defaults = {
        "prompt": "请分析以下案例...",
        "model_id": "deepseek-v4-pro",
        "task_type": TaskType.CASE_ENRICHMENT,
        "request_purpose": RequestPurpose.CASE_ENRICHMENT,
    }
    defaults.update(overrides)
    return LLMCompletionRequest(**defaults)


def _success_response(
    content: str = '{"summary": "test"}',
    model: str = "deepseek-v4-pro",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> httpx.Response:
    """构造模拟成功的 HTTP 响应。"""
    import json

    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "model": model,
    }
    return httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )


def _error_response(
    status_code: int,
    text: str = "error",
) -> httpx.Response:
    """构造模拟错误的 HTTP 响应。"""
    return httpx.Response(
        status_code=status_code,
        text=text,
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )


# ---------------------------------------------------------------------------
# Tests: Successful completion
# ---------------------------------------------------------------------------


class TestSuccessfulCompletion:
    """成功调用场景。"""

    @pytest.mark.asyncio
    async def test_returns_content_and_usage(self, monkeypatch):
        """正常调用返回 content、model_id、usage。"""
        resp = _success_response(
            content='{"summary": "hello"}',
            model="deepseek-v4-pro",
            prompt_tokens=120,
            completion_tokens=80,
        )

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config())
        result = await client.complete_json(_completion_request())

        assert result.content == '{"summary": "hello"}'
        assert result.model_id == "deepseek-v4-pro"
        assert result.usage is not None
        assert result.usage.prompt_tokens == 120
        assert result.usage.completion_tokens == 80
        assert result.usage.total_tokens == 200
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_uses_model_from_response_over_request(self, monkeypatch):
        """响应中的 model 优先于请求中的 model_id。"""
        resp = _success_response(model="deepseek-v4-pro-0324")

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config())
        result = await client.complete_json(_completion_request())

        assert result.model_id == "deepseek-v4-pro-0324"

    @pytest.mark.asyncio
    async def test_works_with_normalizer_config(self, monkeypatch):
        """NormalizerLLMConfig 也能正常工作。"""
        resp = _success_response()

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_normalizer_config())
        result = await client.complete_json(_completion_request())

        assert result.content is not None

    @pytest.mark.asyncio
    async def test_max_tokens_and_temperature_in_payload(self, monkeypatch):
        """max_tokens 和 temperature 正确传递到请求体。"""
        captured = {}

        async def mock_post(self, url, json, timeout):
            captured["json"] = json
            return _success_response()

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config())
        req = _completion_request(max_tokens=2048, temperature=0.7)
        await client.complete_json(req)

        assert captured["json"]["max_tokens"] == 2048
        assert captured["json"]["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_omits_max_tokens_when_none(self, monkeypatch):
        """max_tokens=None 时不传入请求体。"""
        captured = {}

        async def mock_post(self, url, json, timeout):
            captured["json"] = json
            return _success_response()

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config())
        req = _completion_request(max_tokens=None, temperature=None)
        await client.complete_json(req)

        assert "max_tokens" not in captured["json"]
        assert "temperature" not in captured["json"]


# ---------------------------------------------------------------------------
# Tests: Privacy config
# ---------------------------------------------------------------------------


class TestPrivacyConfig:
    """隐私配置校验。"""

    @pytest.mark.asyncio
    async def test_privacy_not_acknowledged_raises(self):
        """privacy_acknowledged=False 时抛出 LLM_PRIVACY_CONFIG_MISSING。"""
        client = LLMClient(_enrichment_config(privacy_acknowledged=False))

        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PRIVACY_CONFIG_MISSING
        assert not exc_info.value.retryable

    @pytest.mark.asyncio
    async def test_normalizer_config_no_privacy_check(self, monkeypatch):
        """NormalizerLLMConfig 没有 privacy_acknowledged 字段，不做隐私检查。"""
        resp = _success_response()

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_normalizer_config())
        result = await client.complete_json(_completion_request())
        assert result.content is not None


# ---------------------------------------------------------------------------
# Tests: Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    """HTTP 错误到 LLMClientError 的映射。"""

    @pytest.mark.asyncio
    async def test_timeout_maps_to_llm_timeout(self, monkeypatch):
        """httpx.TimeoutException 映射为 LLM_TIMEOUT。"""
        async def raise_timeout(*a, **kw):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx.AsyncClient, "post", raise_timeout)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited(self, monkeypatch):
        """HTTP 429 映射为 LLM_RATE_LIMITED，可重试。"""
        resp = _error_response(429, "rate limited")

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_RATE_LIMITED
        assert exc_info.value.retryable is True
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_500_maps_to_provider_error(self, monkeypatch):
        """HTTP 500 映射为 LLM_PROVIDER_ERROR，可重试。"""
        resp = _error_response(500, "internal error")

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_503_maps_to_provider_error(self, monkeypatch):
        """HTTP 503 映射为 LLM_PROVIDER_ERROR，可重试。"""
        resp = _error_response(503, "service unavailable")

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_400_maps_to_provider_error_not_retryable(self, monkeypatch):
        """HTTP 400 映射为 LLM_PROVIDER_ERROR，不可重试。"""
        resp = _error_response(400, "bad request")

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_http_error_maps_to_provider_error(self, monkeypatch):
        """httpx.HTTPError 映射为 LLM_PROVIDER_ERROR，可重试。"""
        async def raise_http_error(*a, **kw):
            raise httpx.ConnectError("connection failed")

        monkeypatch.setattr(httpx.AsyncClient, "post", raise_http_error)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# Tests: Invalid response
# ---------------------------------------------------------------------------


class TestInvalidResponse:
    """无效响应解析场景。"""

    @pytest.mark.asyncio
    async def test_no_choices_raises_invalid_response(self, monkeypatch):
        """响应缺少 choices 字段时抛出 LLM_INVALID_RESPONSE。"""
        resp = httpx.Response(
            status_code=200,
            json={"model": "deepseek-v4-pro"},
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_empty_choices_raises_invalid_response(self, monkeypatch):
        """choices 为空列表时抛出 LLM_INVALID_RESPONSE。"""
        resp = httpx.Response(
            status_code=200,
            json={"choices": [], "model": "deepseek-v4-pro"},
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_no_content_in_message_raises_invalid_response(
        self, monkeypatch,
    ):
        """message 中缺少 content 字段时抛出 LLM_INVALID_RESPONSE。"""
        resp = httpx.Response(
            status_code=200,
            json={
                "choices": [{"message": {"role": "assistant"}, "finish_reason": "stop"}],
                "model": "deepseek-v4-pro",
            },
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_non_json_body_raises_invalid_response(self, monkeypatch):
        """响应体不是有效 JSON 时抛出 LLM_INVALID_RESPONSE。"""
        resp = httpx.Response(
            status_code=200,
            text="not json",
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )

        async def mock_post(*a, **kw):
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE


# ---------------------------------------------------------------------------
# Tests: Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """重试逻辑验证。"""

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_succeeds(self, monkeypatch):
        """超时后重试，第二次成功。"""
        call_count = {"n": 0}

        async def mock_post(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.TimeoutException("timeout")
            return _success_response()

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2))
        result = await client.complete_json(_completion_request())

        assert result.content is not None
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self, monkeypatch):
        """429 后重试，第二次成功。"""
        call_count = {"n": 0}

        async def mock_post(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _error_response(429, "rate limited")
            return _success_response()

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2))
        result = await client.complete_json(_completion_request())

        assert result.content is not None
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_400_error(self, monkeypatch):
        """400 错误不重试。"""
        call_count = {"n": 0}

        async def mock_post(*a, **kw):
            call_count["n"] += 1
            return _error_response(400, "bad request")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=2))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_raises(self, monkeypatch):
        """所有重试耗尽后抛出最后的异常。"""
        call_count = {"n": 0}

        async def mock_post(*a, **kw):
            call_count["n"] += 1
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2))
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT
        assert call_count["n"] == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_retry(self, monkeypatch):
        """max_retries=0 时不重试。"""
        call_count = {"n": 0}

        async def mock_post(*a, **kw):
            call_count["n"] += 1
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(max_retries=0))
        with pytest.raises(LLMClientError):
            await client.complete_json(_completion_request())

        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Tests: Backoff delay
# ---------------------------------------------------------------------------


class TestBackoffDelay:
    """指数退避延迟计算。"""

    def test_backoff_increases_with_attempt(self):
        """延迟随重试次数增加。"""
        assert LLMClient._backoff_delay(0) == 1
        assert LLMClient._backoff_delay(1) == 2
        assert LLMClient._backoff_delay(2) == 4
        assert LLMClient._backoff_delay(3) == 8

    def test_backoff_capped_at_8(self):
        """延迟上限为 8 秒。"""
        assert LLMClient._backoff_delay(10) == 8


# ---------------------------------------------------------------------------
# Tests: LLMClientError
# ---------------------------------------------------------------------------


class TestLLMClientError:
    """异常类属性。"""

    def test_error_attributes(self):
        """LLMClientError 正确携带所有属性。"""
        err = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="timeout",
            retryable=True,
            status_code=503,
        )
        assert err.error_code == ErrorCode.LLM_TIMEOUT
        assert err.message == "timeout"
        assert err.retryable is True
        assert err.status_code == 503
        assert str(err) == "timeout"

    def test_error_defaults(self):
        """默认 retryable=False, status_code=None。"""
        err = LLMClientError(
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            message="bad response",
        )
        assert err.retryable is False
        assert err.status_code is None


# ---------------------------------------------------------------------------
# Tests: URL construction
# ---------------------------------------------------------------------------


class TestURLConstruction:
    """URL 构造。"""

    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_base_url(self, monkeypatch):
        """base_url 末尾的 / 被正确剥离。"""
        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["url"] = url
            return _success_response()

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

        client = LLMClient(_enrichment_config(base_url="https://api.deepseek.com/"))
        await client.complete_json(_completion_request())

        assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"


