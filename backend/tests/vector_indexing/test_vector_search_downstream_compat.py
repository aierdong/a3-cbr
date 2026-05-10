"""向量搜索与下游 ``cbr-retrieval-recommendation`` 的兼容回归（task 5.4）。

本模块固化下游 ``VectorSearchPort`` 的最小请求/响应契约（``cbr-retrieval-recommendation``
design.md 第 「Dependency Contract Snapshot」与「Integration and External Adapters」章节），
确保上游字段漂移可在回归阶段提前暴露：

- 请求侧字段集稳定：``VectorSearchRequest`` / ``VectorSearchFilters`` 至少覆盖下游使用的字段；
- 响应侧字段集稳定：``VectorSearchQueryMetadata`` / ``VectorSearchCandidate``
  至少覆盖下游必填字段（``search_ref``/``index_version``、
  ``case_id``/``vector_id``/``similarity_score``/``index_status``）；
- 端到端契约：注入 fake ``embedding_client`` 与 ``repository``，调用
  ``VectorSearchService.search`` 后所有下游必填字段非空且语义稳定（``index_status``
  恒为 ``searchable``，``search_ref`` 等于 ``query_hash``，``index_version``
  形态包含 ``model_id``）。

Requirements: 2.1, 2.2, 2.4, 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.repository_types import (
    VectorCandidateFilterPayload,
    VectorCandidateRecord,
)
from app.vector_indexing.schemas import (
    EmbeddingResult,
    VectorSearchCandidate,
    VectorSearchFilters,
    VectorSearchIndexStatus,
    VectorSearchQueryMetadata,
    VectorSearchRequest,
)
from app.vector_indexing.search import VectorSearchService

DOWNSTREAM_BATCH_REQUIRED = frozenset({"search_ref", "index_version"})
DOWNSTREAM_CANDIDATE_REQUIRED = frozenset(
    {"case_id", "vector_id", "similarity_score", "index_status"},
)

_DOWNSTREAM_REQUEST_REQUIRED = frozenset({"query_text", "top_k", "filters"})
_DOWNSTREAM_FILTER_REQUIRED = frozenset(
    {
        "brand_id",
        "store_id",
        "problem_type",
        "tags",
        "case_status",
        "case_updated_at_from",
        "case_updated_at_to",
    },
)


def _query_hash(query_text: str) -> str:
    composed = EmbeddingInputComposer().compose_query_input(query_text)
    return hashlib.sha256(composed.text.encode("utf-8")).hexdigest()


def _candidate_record() -> VectorCandidateRecord:
    return VectorCandidateRecord(
        case_id="case_001",
        vector_id="vec_001",
        similarity_score=0.91,
        distance=0.09,
        case_updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        input_content_hash="qh",
        filter_metadata=VectorCandidateFilterPayload(
            brand_id="b1",
            store_id="s1",
            problem_type="pt",
            tags=["t1"],
            case_status="open",
        ),
    )


def test_request_fields_cover_downstream_minimum_contract() -> None:
    """下游 ``VectorSearchPort`` 请求侧最小契约（``query_text``/``top_k``/``filters``）。"""
    fields = frozenset(VectorSearchRequest.model_fields)
    assert _DOWNSTREAM_REQUEST_REQUIRED.issubset(fields)


def test_filter_fields_cover_downstream_minimum_contract() -> None:
    """下游过滤字段最小契约（与 design.md L74-85 ``filters`` 列表一致）。"""
    fields = frozenset(VectorSearchFilters.model_fields)
    assert _DOWNSTREAM_FILTER_REQUIRED.issubset(fields)


def test_query_metadata_fields_cover_downstream_required() -> None:
    """下游 ``VectorCandidateBatch`` 必填信封字段（批次级）出现在 metadata 模型中。"""
    fields = frozenset(VectorSearchQueryMetadata.model_fields)
    assert DOWNSTREAM_BATCH_REQUIRED.issubset(fields)


def test_candidate_fields_cover_downstream_required() -> None:
    """下游 ``VectorCandidate`` 必填字段（候选级）出现在 candidate 模型中。"""
    fields = frozenset(VectorSearchCandidate.model_fields)
    assert DOWNSTREAM_CANDIDATE_REQUIRED.issubset(fields)


@pytest.mark.asyncio
async def test_search_service_emits_downstream_required_envelope() -> None:
    """端到端：service 输出包含全部下游必填字段且语义稳定。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=1024,
            vector=[0.0] * 1024,
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=[_candidate_record()]))
    svc = VectorSearchService(
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(embed_for_query=embed_mock),
        repository=repo,
    )

    request = VectorSearchRequest(query_text="门店客流下降", top_k=5)
    response = await svc.search(request)

    metadata = response.query_metadata
    expected_hash = _query_hash(request.query_text)
    assert metadata.query_hash == expected_hash
    assert metadata.search_ref == expected_hash
    assert metadata.search_ref
    assert metadata.index_version
    assert "bge-large-zh" in metadata.index_version

    assert len(response.items) == 1
    item = response.items[0]
    assert item.case_id
    assert item.vector_id
    assert isinstance(item.similarity_score, float)
    assert 0.0 <= item.similarity_score <= 1.0
    assert item.index_status == VectorSearchIndexStatus.SEARCHABLE


@pytest.mark.asyncio
async def test_search_service_empty_result_still_carries_envelope() -> None:
    """空候选时仍返回稳定的批次信封（``search_ref`` / ``index_version``）。"""
    embed_mock = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=1024,
            vector=[0.0] * 1024,
        ),
    )
    repo = AsyncMock(search=AsyncMock(return_value=[]))
    svc = VectorSearchService(
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(embed_for_query=embed_mock),
        repository=repo,
    )

    response = await svc.search(VectorSearchRequest(query_text="无命中", top_k=10))

    assert response.items == []
    metadata = response.query_metadata
    assert metadata.search_ref
    assert metadata.index_version
    assert "@" in metadata.index_version
    assert metadata.total_candidates_considered == 0
