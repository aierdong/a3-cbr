"""LLMClient / EmbeddingClient / RerankerClient 单元测试。

覆盖：成功调用、超时、限流、供应商错误、无效响应、隐私校验、重试逻辑。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

from app.common.llm_client import (
    EmbeddingClient,
    LLMClient,
    LLMClientError,
    RerankerClient,
)
from app.core.config import (
    EmbeddingConfig,
    EnrichmentLLMConfig,
    NormalizerLLMConfig,
    RerankerConfig,
)
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
        "api_key": "deepseek",
        "model_id": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "timeout_ms": 10000,
        "max_retries": 2,
        "privacy_acknowledged": True,
    }
    defaults.update(overrides)
    return EnrichmentLLMConfig(**defaults)


def _normalizer_config(**overrides) -> NormalizerLLMConfig:
    defaults = {
        "api_key": "deepseek",
        "model_id": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "timeout_ms": 10000,
        "max_retries": 2,
    }
    defaults.update(overrides)
    return NormalizerLLMConfig(**defaults)


def _embedding_config(**overrides) -> EmbeddingConfig:
    defaults = {
        "api_key": "embed-key",
        "model_id": "bge-large-zh",
        "base_url": "https://qianfan.baidubce.com/v2",
        "timeout_ms": 60000,
        "max_retries": 3,
    }
    defaults.update(overrides)
    return EmbeddingConfig(**defaults)


def _reranker_config(**overrides) -> RerankerConfig:
    defaults = {
        "api_key": "rerank-key",
        "model_id": "qwen3-reranker-8b",
        "base_url": "https://qianfan.baidubce.com/v2",
        "timeout_ms": 45000,
        "max_retries": 2,
    }
    defaults.update(overrides)
    return RerankerConfig(**defaults)


def _completion_request(**overrides) -> LLMCompletionRequest:
    defaults = {
        "prompt": "请分析以下案例...",
        "model_id": "deepseek-v4-flash",
        "task_type": TaskType.CASE_ENRICHMENT,
        "request_purpose": RequestPurpose.CASE_ENRICHMENT,
    }
    defaults.update(overrides)
    return LLMCompletionRequest(**defaults)


def _stub_chat_completion(
    content: str = '{"summary": "test"}',
    model: str = "deepseek-v4-flash",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> SimpleNamespace:
    """构造 SDK ChatCompletion 形态的 stub。"""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            ),
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        model=model,
    )


def _mock_llm_async_client(completion: SimpleNamespace) -> MagicMock:
    m = MagicMock()
    m.chat.completions.create = AsyncMock(return_value=completion)
    return m


def _request429() -> httpx.Request:
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def _resp(code: int) -> httpx.Response:
    return httpx.Response(code, request=_request429())


# ---------------------------------------------------------------------------
# Tests: Successful completion
# ---------------------------------------------------------------------------


class TestSuccessfulCompletion:
    """成功调用场景。"""

    @pytest.mark.asyncio
    async def test_returns_content_and_usage(self):
        """正常调用返回 content、model_id、usage。"""
        comp = _stub_chat_completion(
            content='{"summary": "hello"}',
            prompt_tokens=120,
            completion_tokens=80,
        )
        client = LLMClient(_enrichment_config(), _async_client=_mock_llm_async_client(comp))
        result = await client.complete_json(_completion_request())

        assert result.content == '{"summary": "hello"}'
        assert result.model_id == "deepseek-v4-flash"
        assert result.usage is not None
        assert result.usage.prompt_tokens == 120
        assert result.usage.completion_tokens == 80
        assert result.usage.total_tokens == 200
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_uses_model_from_response_over_request(self):
        """响应中的 model 优先于请求中的 model_id。"""
        comp = _stub_chat_completion(model="deepseek-v4-flash-0324")
        client = LLMClient(_enrichment_config(), _async_client=_mock_llm_async_client(comp))
        result = await client.complete_json(_completion_request())

        assert result.model_id == "deepseek-v4-flash-0324"

    @pytest.mark.asyncio
    async def test_works_with_normalizer_config(self):
        """NormalizerLLMConfig 也能正常工作。"""
        comp = _stub_chat_completion()
        client = LLMClient(_normalizer_config(), _async_client=_mock_llm_async_client(comp))
        result = await client.complete_json(_completion_request())

        assert result.content is not None

    @pytest.mark.asyncio
    async def test_max_tokens_and_temperature_passed_to_sdk(self):
        """max_tokens 和 temperature 传入 SDK。"""
        captured: dict = {}

        async def capture_create(**kwargs):
            captured.update(kwargs)
            return _stub_chat_completion()

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=capture_create)

        client = LLMClient(_enrichment_config(), _async_client=mock)
        req = _completion_request(max_tokens=2048, temperature=0.7)
        await client.complete_json(req)

        assert captured["max_tokens"] == 2048
        assert captured["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_omits_max_tokens_when_none(self):
        """max_tokens=None 时不传入 SDK。"""
        captured: dict = {}

        async def capture_create(**kwargs):
            captured.update(kwargs)
            return _stub_chat_completion()

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=capture_create)

        client = LLMClient(_enrichment_config(), _async_client=mock)
        req = _completion_request(max_tokens=None, temperature=None)
        await client.complete_json(req)

        assert "max_tokens" not in captured
        assert "temperature" not in captured


# ---------------------------------------------------------------------------
# Tests: Privacy config
# ---------------------------------------------------------------------------


class TestPrivacyConfig:
    """隐私配置校验。"""

    @pytest.mark.asyncio
    async def test_privacy_not_acknowledged_raises(self):
        """privacy_acknowledged=False 时抛出 LLM_PRIVACY_CONFIG_MISSING。"""
        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(return_value=_stub_chat_completion())
        client = LLMClient(
            _enrichment_config(privacy_acknowledged=False),
            _async_client=mock,
        )

        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PRIVACY_CONFIG_MISSING
        assert not exc_info.value.retryable
        mock.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_normalizer_config_no_privacy_check(self):
        """NormalizerLLMConfig 没有 privacy_acknowledged 字段，不做隐私检查。"""
        comp = _stub_chat_completion()
        client = LLMClient(_normalizer_config(), _async_client=_mock_llm_async_client(comp))
        result = await client.complete_json(_completion_request())
        assert result.content is not None


# ---------------------------------------------------------------------------
# Tests: Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    """SDK 错误到 LLMClientError 的映射。"""

    @pytest.mark.asyncio
    async def test_timeout_maps_to_llm_timeout(self):
        """APITimeoutError 映射为 LLM_TIMEOUT。"""

        async def raise_timeout(**kwargs):
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_timeout)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited(self):
        """HTTP 429 映射为 LLM_RATE_LIMITED，可重试。"""

        async def raise_429(**kwargs):
            raise openai.RateLimitError(
                "rate limited",
                response=_resp(429),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_429)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_RATE_LIMITED
        assert exc_info.value.retryable is True
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_500_maps_to_provider_error(self):
        """HTTP 500 映射为 LLM_PROVIDER_ERROR，可重试。"""

        async def raise_500(**kwargs):
            raise openai.APIStatusError(
                "internal error",
                response=_resp(500),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_500)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_503_maps_to_provider_error(self):
        """HTTP 503 映射为 LLM_PROVIDER_ERROR，可重试。"""

        async def raise_503(**kwargs):
            raise openai.APIStatusError(
                "service unavailable",
                response=_resp(503),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_503)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_400_maps_to_provider_error_not_retryable(self):
        """HTTP 400 映射为 LLM_PROVIDER_ERROR，不可重试。"""

        async def raise_400(**kwargs):
            raise openai.APIStatusError(
                "bad request",
                response=_resp(400),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_400)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_connection_error_maps_to_provider_error(self):
        """APIConnectionError 映射为 LLM_PROVIDER_ERROR，可重试。"""
        req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")

        async def raise_conn(**kwargs):
            raise openai.APIConnectionError(message="connection failed", request=req)

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=raise_conn)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
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
    async def test_no_choices_raises_invalid_response(self):
        """响应缺少 choices 时抛出 LLM_INVALID_RESPONSE。"""
        bad = SimpleNamespace(choices=[], model="deepseek-v4-flash")
        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(return_value=bad)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_empty_choices_raises_invalid_response(self):
        """choices 为空列表时抛出 LLM_INVALID_RESPONSE。"""
        bad = SimpleNamespace(choices=[], model="deepseek-v4-flash")
        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(return_value=bad)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_no_content_in_message_raises_invalid_response(self):
        """message 中缺少 content 字段时抛出 LLM_INVALID_RESPONSE。"""
        bad = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(role="assistant"),
                    finish_reason="stop",
                ),
            ],
            model="deepseek-v4-flash",
        )
        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(return_value=bad)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
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

        async def flaky(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise openai.APITimeoutError("timeout")
            return _stub_chat_completion()

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=flaky)

        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2), _async_client=mock)
        result = await client.complete_json(_completion_request())

        assert result.content is not None
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self, monkeypatch):
        """429 后重试，第二次成功。"""
        call_count = {"n": 0}

        async def flaky(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise openai.RateLimitError(
                    "rate limited",
                    response=_resp(429),
                    body=None,
                )
            return _stub_chat_completion()

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=flaky)

        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2), _async_client=mock)
        result = await client.complete_json(_completion_request())

        assert result.content is not None
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_400_error(self):
        """400 错误不重试。"""
        call_count = {"n": 0}

        async def bad(**kwargs):
            call_count["n"] += 1
            raise openai.APIStatusError(
                "bad request",
                response=_resp(400),
                body=None,
            )

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=bad)

        client = LLMClient(_enrichment_config(max_retries=2), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_raises(self, monkeypatch):
        """所有重试耗尽后抛出最后的异常。"""
        call_count = {"n": 0}

        async def always_timeout(**kwargs):
            call_count["n"] += 1
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=always_timeout)

        monkeypatch.setattr(LLMClient, "_backoff_delay", staticmethod(lambda _: 0))

        client = LLMClient(_enrichment_config(max_retries=2), _async_client=mock)
        with pytest.raises(LLMClientError) as exc_info:
            await client.complete_json(_completion_request())

        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT
        assert call_count["n"] == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_retry(self):
        """max_retries=0 时不重试。"""
        call_count = {"n": 0}

        async def always_timeout(**kwargs):
            call_count["n"] += 1
            raise openai.APITimeoutError("timeout")

        mock = MagicMock()
        mock.chat.completions.create = AsyncMock(side_effect=always_timeout)

        client = LLMClient(_enrichment_config(max_retries=0), _async_client=mock)
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
# Tests: EmbeddingClient
# ---------------------------------------------------------------------------


class TestEmbeddingClient:
    """Embedding SDK 封装。"""

    @pytest.mark.asyncio
    async def test_embed_texts_returns_vectors_ordered(self):
        """按 index 排序后返回与输入顺序一致的向量。"""
        stub_resp = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.1, 0.2]),
                SimpleNamespace(index=0, embedding=[0.3, 0.4]),
            ],
        )
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(return_value=stub_resp)

        client = EmbeddingClient(_embedding_config(max_retries=0), _async_client=mock)
        out = await client.embed_texts(["a", "b"])

        assert out == [[0.3, 0.4], [0.1, 0.2]]
        mock.embeddings.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embed_empty_returns_empty(self):
        """空输入不调用嵌入接口。"""
        mock = MagicMock()
        client = EmbeddingClient(_embedding_config(), _async_client=mock)
        assert await client.embed_texts([]) == []
        mock.embeddings.create.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: RerankerClient
# ---------------------------------------------------------------------------


class TestRerankerClient:
    """Rerank ``post /rerank`` 封装。"""

    @pytest.mark.asyncio
    async def test_rerank_scores_aligned_to_documents(self):
        """根据 results.index 还原与 documents 同序的分值。"""
        body = {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.5},
            ],
        }
        mock = MagicMock()
        mock.post = AsyncMock(return_value=body)

        client = RerankerClient(_reranker_config(max_retries=0), _async_client=mock)
        scores = await client.rerank_scores(query="q", documents=["d0", "d1"])

        assert scores == [0.5, 0.9]
        mock.post.assert_awaited_once()
        assert mock.post.call_args[0][0] == "/rerank"
        assert mock.post.call_args[1]["body"]["model"] == "qwen3-reranker-8b"

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self):
        """空文档列表不发起 rerank 请求。"""
        mock = MagicMock()
        client = RerankerClient(_reranker_config(), _async_client=mock)
        assert await client.rerank_scores(query="q", documents=[]) == []
        mock.post.assert_not_called()
