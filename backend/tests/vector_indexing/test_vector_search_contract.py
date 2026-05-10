"""向量搜索响应契约守卫（Requirement 5.5 / design Data Contracts）。

固化 VectorSearchService 与搜索 schema 边界：无推荐理由、reranker、加权聚合与展示序字段；
Pydantic 模型配置为禁止未知字段；search 模块不显式依赖推荐编排类型。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.schemas import (
    EmbeddingResult,
    VectorSearchCandidate,
    VectorSearchQueryMetadata,
    VectorSearchRequest,
    VectorSearchResponse,
)
from app.vector_indexing.search import VectorSearchService


_EXPECTED_VECTOR_SEARCH_RESPONSE_FIELDS = frozenset({"items", "query_metadata"})

_EXPECTED_VECTOR_SEARCH_CANDIDATE_FIELDS = frozenset(
    {
        "case_id",
        "vector_id",
        "similarity_score",
        "distance",
        "case_updated_at",
        "input_content_hash",
        "filter_metadata",
    },
)

_EXPECTED_VECTOR_SEARCH_QUERY_METADATA_FIELDS = frozenset(
    {
        "query_hash",
        "model_id",
        "dimension",
        "filters_applied",
        "total_candidates_considered",
    },
)

_FORBIDDEN_PRIMITIVE_FIELD_NAMES = frozenset(
    {
        "recommendation_reason",
        "recommendation_explanation",
        "reranker_score",
        "aggregated_score",
        "weighted_score",
        "feedback_score",
        "feedback_label",
        "final_display_order",
        "display_rank",
        "business_score",
        "policy_score",
    },
)


def test_vector_search_schema_fieldsets_match_contract() -> None:
    """schema 字段集与契约快照一致；变更须同步更新本模块常量。"""
    assert frozenset(VectorSearchResponse.model_fields) == _EXPECTED_VECTOR_SEARCH_RESPONSE_FIELDS
    assert frozenset(VectorSearchCandidate.model_fields) == _EXPECTED_VECTOR_SEARCH_CANDIDATE_FIELDS
    assert (
        frozenset(VectorSearchQueryMetadata.model_fields)
        == _EXPECTED_VECTOR_SEARCH_QUERY_METADATA_FIELDS
    )


def test_vector_search_schemas_exclude_forbidden_recommendation_fields() -> None:
    """禁止推荐理由、精排分、聚合分、反馈与展示序等字段出现在搜索原语模型中。"""
    for name in _FORBIDDEN_PRIMITIVE_FIELD_NAMES:
        assert name not in VectorSearchResponse.model_fields
        assert name not in VectorSearchCandidate.model_fields
        assert name not in VectorSearchQueryMetadata.model_fields


def test_vector_search_response_rejects_unknown_fields() -> None:
    """extra forbid：未知字段（含 recommendation_reason）校验失败。"""
    base_meta = {
        "query_hash": "a" * 64,
        "model_id": "bge-large-zh",
        "dimension": 4,
        "filters_applied": {},
        "total_candidates_considered": None,
    }
    payload = {
        "items": [],
        "query_metadata": base_meta,
        "recommendation_reason": "must-not-appear",
    }
    with pytest.raises(ValidationError):
        VectorSearchResponse.model_validate(payload)


def test_vector_search_service_init_dependencies_are_primitive_only() -> None:
    """搜索服务仅注入 composer、embedding_client、repository。"""
    sig = inspect.signature(VectorSearchService.__init__)
    params = [p for n, p in sig.parameters.items() if n != "self"]
    assert [p.name for p in params] == ["composer", "embedding_client", "repository"]
    assert params[2].kind == inspect.Parameter.KEYWORD_ONLY


def test_vector_search_service_search_module_has_no_rerank_or_recommendation_keywords() -> None:
    """search.py 源码不出现推荐编排相关类型名碎片。"""
    backend_root = Path(__file__).resolve().parents[2]
    src = (backend_root / "app" / "vector_indexing" / "search.py").read_text(encoding="utf-8")
    for token in ("Reranker", "RecommendationCopy", "AggregatedScore"):
        assert token not in src


@pytest.mark.asyncio
async def test_vector_search_search_happy_path_only_uses_embed_and_repository() -> None:
    """合法路径仅 await embed_for_query 与 repository.search，无其他编排依赖。"""
    embed_for_query = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=4,
            vector=[0.1, 0.2, 0.3, 0.4],
        ),
    )
    embedding_client = AsyncMock(embed_for_query=embed_for_query)
    repo = AsyncMock(search=AsyncMock(return_value=[]))
    svc = VectorSearchService(
        composer=EmbeddingInputComposer(),
        embedding_client=embedding_client,
        repository=repo,
    )
    req = VectorSearchRequest(query_text="测试查询", top_k=3)
    resp = await svc.search(req)

    embed_for_query.assert_awaited_once()
    repo.search.assert_awaited_once()
    assert resp.items == []
    assert isinstance(resp.query_metadata, VectorSearchQueryMetadata)
