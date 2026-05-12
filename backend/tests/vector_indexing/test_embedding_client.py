"""向量索引 EmbeddingClient：超时/重试分离、响应校验与日志边界。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from app.core.llm_client import LLMClientError
from app.core.config import EmbeddingConfig
from app.core.errors import ErrorCode
from app.vector_indexing.embedding_client import EmbeddingClient
from app.vector_indexing.schemas import EmbeddingRequest


def _cfg(**overrides: object) -> EmbeddingConfig:
    base = dict(
        api_key="k",
        model_id="bge-large-zh",
        base_url="https://example.com/v2",
        vector_dimension=4,
        index_timeout_ms=30000,
        index_max_retries=2,
        search_timeout_ms=5000,
        search_max_retries=0,
    )
    base.update(overrides)
    return EmbeddingConfig(**base)  # type: ignore[arg-type]


def _request(text: str = "x") -> EmbeddingRequest:
    return EmbeddingRequest(
        text=text,
        case_id="case-1",
        correlation_id="corr-1",
        content_fingerprint="fp9ab",
    )


class TestVectorIndexingEmbeddingClient:
    """``EmbeddingClient`` 索引/搜索路径策略与错误映射测试。"""

    @pytest.mark.asyncio
    async def test_embed_for_index_success_sorted_by_index(self) -> None:
        """索引路径成功时应返回维度匹配的向量。"""
        stub_resp = SimpleNamespace(
            data=[
                SimpleNamespace(index=99, embedding=[0.5, 0.6, 0.7, 0.8]),
            ],
        )
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(return_value=stub_resp)

        client = EmbeddingClient(_cfg(), _async_client_index=mock, _async_client_search=mock)
        req = _request()
        result = await client.embed_for_index(req)

        assert result.embedding_model_id == "bge-large-zh"
        assert result.embedding_dimension == 4
        assert result.vector == [0.5, 0.6, 0.7, 0.8]
        mock.embeddings.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embed_for_query_uses_search_only_attempt(self) -> None:
        """搜索路径超时时只尝试一次且 ``retryable`` 为 False。"""
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(
            side_effect=openai.APITimeoutError(MagicMock()),
        )
        client = EmbeddingClient(_cfg(), _async_client_index=mock, _async_client_search=mock)

        with pytest.raises(LLMClientError) as ei:
            await client.embed_for_query(_request())

        assert ei.value.error_code == ErrorCode.EMBEDDING_TIMEOUT
        assert ei.value.retryable is False
        assert mock.embeddings.create.await_count == 1

    @pytest.mark.asyncio
    async def test_embed_for_index_retries_then_success(self) -> None:
        """索引路径在临时超时后应按 ``index_max_retries`` 重试并成功。"""
        ok = SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1.0, 0.0, 0.0, 0.0])],
        )
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(
            side_effect=[
                openai.APITimeoutError(MagicMock()),
                ok,
            ],
        )
        client = EmbeddingClient(_cfg(), _async_client_index=mock, _async_client_search=mock)
        result = await client.embed_for_index(_request())
        assert result.vector == [1.0, 0.0, 0.0, 0.0]
        assert mock.embeddings.create.await_count == 2

    @pytest.mark.asyncio
    async def test_dimension_mismatch_maps_stable_error(self) -> None:
        """维度与 ``EmbeddingConfig.vector_dimension`` 不符时映射为固定错误码。"""
        stub = SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[1.0, 2.0])],
        )
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(return_value=stub)
        client = EmbeddingClient(_cfg(vector_dimension=4), _async_client_index=mock)

        with pytest.raises(LLMClientError) as ei:
            await client.embed_for_index(_request())

        assert ei.value.error_code == ErrorCode.EMBEDDING_DIMENSION_MISMATCH
        assert ei.value.retryable is False

    @pytest.mark.asyncio
    async def test_missing_data_maps_invalid_response(self) -> None:
        """响应缺少 ``data`` 时映射为 ``EMBEDDING_INVALID_RESPONSE``。"""
        stub = SimpleNamespace(data=None)
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(return_value=stub)
        client = EmbeddingClient(_cfg(), _async_client_index=mock)

        with pytest.raises(LLMClientError) as ei:
            await client.embed_for_index(_request())

        assert ei.value.error_code == ErrorCode.EMBEDDING_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_rate_limit_mapped(self) -> None:
        """搜索路径应将 SDK 限流异常映射为 ``EMBEDDING_RATE_LIMITED``。"""
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(
            side_effect=openai.RateLimitError("429", response=MagicMock(), body=None),
        )
        client = EmbeddingClient(_cfg(), _async_client_index=mock, _async_client_search=mock)

        with pytest.raises(LLMClientError) as ei:
            await client.embed_for_query(_request())

        assert ei.value.error_code == ErrorCode.EMBEDDING_RATE_LIMITED
        assert ei.value.retryable is False
        assert ei.value.status_code == 503

    @pytest.mark.asyncio
    async def test_logs_do_not_include_plaintext_or_vectors(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """日志 extra 不得包含输入正文或向量数组字面量。"""
        stub = SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3, 0.4])],
        )
        mock = MagicMock()
        mock.embeddings.create = AsyncMock(return_value=stub)
        client = EmbeddingClient(_cfg(), _async_client_index=mock)

        secret = "SECRET_FULL_CASE_BODY"
        await client.embed_for_index(_request(text=secret))

        combined = caplog.text + "".join(
            str(r.__dict__) for r in caplog.records
        )
        assert secret not in combined
        assert "[0.1" not in combined and "0.1," not in combined.replace(" ", "")
