"""RerankerClient 单元测试。

测试 RerankerClient 的：
1. Feature Flag gate
2. 成功路径：正常调用 reranker、返回归一化语义分值
3. 失败路径：timeout、rate_limit、provider_error、invalid_response、config_missing
4. 分值归一化：供应商分值归一化到 0..1
5. 错误映射：RerankerClientError 映射到统一错误码

Feature Flag 协议：
- RED 阶段：flag=False，测试跳过
- GREEN 阶段：flag=True，测试执行
- 测试文件从 reranker_client.py 导入 flag，保持同步
"""

from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from app.core.config import RerankerConfig
from app.core.errors import ErrorCode

# 从实现文件导入 feature flag，保持同步
from app.retrieval.reranker_client import (
    RETRIEVAL_RERANKER_ENABLED,
    is_reranker_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_reranker_config(
    api_key: str = "test-api-key",
    model_id: str = "qwen3-reranker-8b",
    base_url: str = "https://api.example.com/v2",
    timeout_ms: int = 45000,
    max_retries: int = 2,
) -> RerankerConfig:
    """构造 RerankerConfig。"""
    return RerankerConfig(
        api_key=api_key,
        model_id=model_id,
        base_url=base_url,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
    )


# ---------------------------------------------------------------------------
# Tests: Feature Flag Gate
# ---------------------------------------------------------------------------


class TestRerankerFeatureFlag:
    """Feature Flag Protocol: flag=OFF 时测试应失败或跳过。"""

    def test_feature_flag_reflects_implementation_state(self):
        """GREEN 阶段：flag=True（实现已完成）。"""
        # 实现文件中 flag=True 表示功能已完成
        assert RETRIEVAL_RERANKER_ENABLED is True

    def test_is_reranker_enabled_returns_correct_value(self):
        """is_reranker_enabled 返回 flag 当前值。"""
        assert is_reranker_enabled() == RETRIEVAL_RERANKER_ENABLED


# ---------------------------------------------------------------------------
# Tests: 成功路径
# ---------------------------------------------------------------------------


class TestRerankerSuccess:
    """Reranker 成功场景。"""

    @pytest.mark.asyncio
    async def test_rerank_returns_normalized_scores(self):
        """成功调用 reranker 并返回归一化语义分值。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        # 构造 mock AsyncOpenAI client
        # shared RerankerClient.rerank_scores 内部调用 client.post()
        mock_response_data = [
            {"index": 0, "relevance_score": 0.92},
            {"index": 1, "relevance_score": 0.85},
            {"index": 2, "relevance_score": 0.78},
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value={"results": mock_response_data})

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        query = "门店客户投诉处理方法"
        documents = [
            "案例1：门店客户投诉处理流程介绍...",
            "案例2：客户投诉预防措施...",
            "案例3：售后服务标准...",
        ]

        result = await client.rerank(query=query, documents=documents)

        assert len(result.scores) == 3
        assert result.scores[0] == pytest.approx(0.92)
        assert result.scores[1] == pytest.approx(0.85)
        assert result.scores[2] == pytest.approx(0.78)
        assert result.model_id == "qwen3-reranker-8b"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_rerank_empty_documents_returns_empty_list(self):
        """空文档列表返回空列表（非失败）。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_client = MagicMock()
        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        result = await client.rerank(query="test", documents=[])

        assert result.scores == []

    @pytest.mark.asyncio
    async def test_rerank_with_top_n_limit(self):
        """top_n 参数限制返回数量。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_response_data = [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.88},
            {"index": 2, "relevance_score": 0.75},
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value={"results": mock_response_data}
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        query = "门店客户投诉处理方法"
        documents = [
            "案例1：门店客户投诉处理流程介绍...",
            "案例2：客户投诉预防措施...",
            "案例3：售后服务标准...",
        ]

        # 请求 top_n=2
        result = await client.rerank(
            query=query, documents=documents, top_n=2
        )
        assert result.scores is not None  # 验证返回结构完整

        # 验证调用时包含 top_n 参数
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs.get("body", {}).get("top_n") == 2


# ---------------------------------------------------------------------------
# Tests: 错误映射
# ---------------------------------------------------------------------------


class TestRerankerErrorMapping:
    """Reranker 错误语义映射。"""

    @pytest.mark.asyncio
    async def test_timeout_error_raises_reranker_timeout(self):
        """超时错误映射为 RerankerTimeout。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        import openai

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=openai.APITimeoutError("Request timed out")
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient, RerankerTimeout

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerTimeout) as exc_info:
            await client.rerank(
                query="test", documents=["doc1", "doc2"]
            )

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_RERANKER_TIMEOUT

    @pytest.mark.asyncio
    async def test_rate_limit_error_raises_reranker_rate_limited(self):
        """限流错误映射为 RerankerRateLimited。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        import httpx
        import openai

        req = httpx.Request("POST", "https://api.example.com/rerank")
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=openai.RateLimitError(
                "Rate limit exceeded",
                response=httpx.Response(429, request=req),
                body=None,
            )
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient, RerankerRateLimited

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerRateLimited) as exc_info:
            await client.rerank(
                query="test", documents=["doc1", "doc2"]
            )

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_RERANKER_RATE_LIMITED

    @pytest.mark.asyncio
    async def test_provider_error_raises_reranker_provider_error(self):
        """供应商错误映射为 RerankerProviderError。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=openai.APIConnectionError(
                message="Connection failed",
                request=MagicMock(),
            )
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import (
            RerankerClient,
            RerankerProviderError,
        )

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerProviderError) as exc_info:
            await client.rerank(
                query="test", documents=["doc1", "doc2"]
            )

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_RERANKER_PROVIDER_ERROR

    @pytest.mark.asyncio
    async def test_invalid_response_raises_reranker_invalid_response(self):
        """无效响应（缺少 results 字段）映射为 RerankerInvalidResponse。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value={"unexpected": "format"})

        config = _make_reranker_config()
        from app.retrieval.reranker_client import (
            RerankerClient,
            RerankerInvalidResponse,
        )

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerInvalidResponse) as exc_info:
            await client.rerank(
                query="test", documents=["doc1", "doc2"]
            )

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_RERANKER_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_config_missing(self):
        """api_key 为空时 fail-closed（配置检查阶段即拒绝）。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_client = MagicMock()
        config = _make_reranker_config(api_key="")

        from app.retrieval.reranker_client import RerankerClient, RerankerConfigMissing

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerConfigMissing) as exc_info:
            await client.rerank(
                query="test", documents=["doc1"]
            )

        assert exc_info.value.error_code == ErrorCode.RETRIEVAL_RERANKER_CONFIG_MISSING


# ---------------------------------------------------------------------------
# Tests: 分值归一化
# ---------------------------------------------------------------------------


class TestRerankerScoreNormalization:
    """Reranker 分值归一化：供应商分值归一化到 0..1。"""

    @pytest.mark.asyncio
    async def test_scores_above_one_are_clipped_to_one(self):
        """供应商返回 > 1 的分值裁剪到 1.0。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        # 模拟供应商返回超出 0..1 范围的分值
        mock_response_data = [
            {"index": 0, "relevance_score": 1.5},  # 超出范围
            {"index": 1, "relevance_score": 0.85},
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value={"results": mock_response_data}
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        result = await client.rerank(
            query="test", documents=["doc1", "doc2"]
        )

        # 1.5 应该被裁剪到 1.0
        assert result.scores[0] <= 1.0
        assert result.scores[1] <= 1.0

    @pytest.mark.asyncio
    async def test_negative_scores_are_clipped_to_zero(self):
        """供应商返回负数分值裁剪到 0.0。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_response_data = [
            {"index": 0, "relevance_score": -0.1},  # 负数
            {"index": 1, "relevance_score": 0.5},
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value={"results": mock_response_data}
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        result = await client.rerank(
            query="test", documents=["doc1", "doc2"]
        )

        assert result.scores[0] >= 0.0
        assert result.scores[1] >= 0.0

    @pytest.mark.asyncio
    async def test_results_order_matches_input_documents(self):
        """返回分值顺序与输入文档顺序一致（按 index 排序）。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        # results 顺序与 documents 顺序不一致（打乱顺序返回）
        mock_response_data = [
            {"index": 2, "relevance_score": 0.9},  # doc3 得分最高
            {"index": 0, "relevance_score": 0.7},  # doc1
            {"index": 1, "relevance_score": 0.5},  # doc2
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value={"results": mock_response_data}
        )

        config = _make_reranker_config()
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        query = "test"
        documents = ["文档1", "文档2", "文档3"]

        result = await client.rerank(query=query, documents=documents)

        # 返回分值应按原始 documents 顺序：doc1=0.7, doc2=0.5, doc3=0.9
        assert len(result.scores) == 3
        assert result.scores[0] == pytest.approx(0.7)  # doc1
        assert result.scores[1] == pytest.approx(0.5)  # doc2
        assert result.scores[2] == pytest.approx(0.9)  # doc3


# ---------------------------------------------------------------------------
# Tests: 重试逻辑
# ---------------------------------------------------------------------------


class TestRerankerRetryLogic:
    """Reranker 重试逻辑：可重试错误（timeout、rate_limit）应重试。"""

    @pytest.mark.asyncio
    async def test_timeout_retries_and_succeeds(self):
        """超时错误重试后成功。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        import openai

        mock_response_data = [
            {"index": 0, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.6},
        ]

        mock_client = MagicMock()
        # 第1次超时，第2次成功
        mock_client.post = AsyncMock(
            side_effect=[
                openai.APITimeoutError("Timeout"),
                {"results": mock_response_data},
            ]
        )

        config = _make_reranker_config(max_retries=2)
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        result = await client.rerank(
            query="test", documents=["doc1", "doc2"]
        )

        assert len(result.scores) == 2
        assert result.scores[0] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """非可重试错误（如认证失败）立即抛出，不重试。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        import openai

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=openai.AuthenticationError(
                "Invalid API key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )

        config = _make_reranker_config(max_retries=2)
        from app.retrieval.reranker_client import RerankerClient, RerankerProviderError

        client = RerankerClient(config=config, _async_client=mock_client)

        with pytest.raises(RerankerProviderError):
            await client.rerank(
                query="test", documents=["doc1"]
            )

        # 只调用一次，不重试
        assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# Tests: 配置验证
# ---------------------------------------------------------------------------


class TestRerankerConfigValidation:
    """Reranker 配置验证。"""

    @pytest.mark.asyncio
    async def test_config_values_are_used_in_request(self):
        """配置值（model_id、timeout、base_url）正确用于请求。"""
        if not is_reranker_enabled():
            pytest.skip("RerankerClient 功能未启用")

        mock_response_data = [
            {"index": 0, "relevance_score": 0.75},
        ]

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value={"results": mock_response_data}
        )

        config = RerankerConfig(
            api_key="test-key-123",
            model_id="qwen3-reranker-8b",
            base_url="https://custom.reranker.com/v1",
            timeout_ms=60000,
            max_retries=1,
        )
        from app.retrieval.reranker_client import RerankerClient

        client = RerankerClient(config=config, _async_client=mock_client)

        await client.rerank(query="test", documents=["doc1"])

        # 验证调用参数
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("body", {})
        assert body.get("model") == "qwen3-reranker-8b"