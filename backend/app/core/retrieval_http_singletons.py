"""推荐链路使用的 LLM / Rerank HTTP 客户端进程级单例。

在应用 lifespan 启动时初始化，避免每个请求在 ``Depends`` 中重复构造 ``AsyncOpenAI``。
单测等未走 lifespan 的场景由 ``ensure_retrieval_http_singletons_initialized`` 惰性补初始化。
"""

from __future__ import annotations

import logging
import time
from threading import Lock

from app.core.config import get_app_config
from app.core.llm_client import LLMClient, RerankerClient as SharedRerankerClient

logger = logging.getLogger(__name__)

_lock = Lock()
_normalizer_llm: LLMClient | None = None
_enrichment_llm: LLMClient | None = None
_shared_rerank_http: SharedRerankerClient | None = None
_initialized: bool = False


def init_retrieval_http_singletons() -> None:
    """根据 ``get_app_config()`` 构建单例；线程安全且幂等。"""
    global _normalizer_llm, _enrichment_llm, _shared_rerank_http, _initialized
    with _lock:
        if _initialized:
            return
        cfg = get_app_config()
        t0 = time.perf_counter()
        _normalizer_llm = LLMClient(config=cfg.normalizer_llm)
        t1 = time.perf_counter()
        _enrichment_llm = LLMClient(config=cfg.enrichment_llm)
        t2 = time.perf_counter()
        _shared_rerank_http = SharedRerankerClient(config=cfg.reranker)
        t3 = time.perf_counter()
        _initialized = True
        logger.info(
            "retrieval_http_singletons_init_ms normalizer=%.1f enrichment=%.1f "
            "rerank_http=%.1f total=%.1f",
            (t1 - t0) * 1000.0,
            (t2 - t1) * 1000.0,
            (t3 - t2) * 1000.0,
            (t3 - t0) * 1000.0,
        )


def ensure_retrieval_http_singletons_initialized() -> None:
    """保证单例已构建（无 lifespan 时由路由依赖首次调用）。"""
    if not _initialized:
        init_retrieval_http_singletons()


def get_singleton_normalizer_llm_client() -> LLMClient:
    """返回规范化用 ``LLMClient`` 单例。"""
    ensure_retrieval_http_singletons_initialized()
    assert _normalizer_llm is not None
    return _normalizer_llm


def get_singleton_enrichment_llm_client() -> LLMClient:
    """返回富化 / 推荐文案用 ``LLMClient`` 单例。"""
    ensure_retrieval_http_singletons_initialized()
    assert _enrichment_llm is not None
    return _enrichment_llm


def get_singleton_shared_rerank_http_client() -> SharedRerankerClient:
    """返回 ``app.core.llm_client.RerankerClient``（rerank HTTP）单例。"""
    ensure_retrieval_http_singletons_initialized()
    assert _shared_rerank_http is not None
    return _shared_rerank_http


def reset_retrieval_http_singletons_for_tests() -> None:
    """测试用：清空单例（勿在生产调用）。"""
    global _normalizer_llm, _enrichment_llm, _shared_rerank_http, _initialized
    with _lock:
        _normalizer_llm = None
        _enrichment_llm = None
        _shared_rerank_http = None
        _initialized = False
