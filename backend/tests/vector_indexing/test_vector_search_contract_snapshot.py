"""向量搜索契约快照测试（task 5.4）。

固化向量搜索请求/响应的最小字段契约（批次级 ``search_ref``/``index_version``，候选级
``case_id``/``vector_id``/``similarity_score``/``index_status``），并覆盖：

- 字段集白名单（与下游 ``cbr-retrieval-recommendation`` design.md
  ``VectorSearchPort`` 必填项的并集一致）；
- 序列化快照：固定输入下 ``model_dump(mode="json")`` 的顶层 keys 与候选 keys
  保持稳定，``index_status`` 为字面量 ``"searchable"``；
- 失败路径：批次或候选缺少下游必填字段时，``VectorSearchResponse.model_validate``
  必须抛出 ``pydantic.ValidationError``（即 ``invalid_response`` 语义）；
- 字段类型/语义稳定：``similarity_score`` 为 ``float`` 且范围 ``0..1``；
  ``index_status`` 字面量集合 ``{"searchable"}``。

Requirements: 2.1, 2.2, 2.4, 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.vector_indexing.schemas import (
    VectorSearchCandidate,
    VectorSearchFilters,
    VectorSearchIndexStatus,
    VectorSearchQueryMetadata,
    VectorSearchRequest,
    VectorSearchResponse,
)

_DOWNSTREAM_BATCH_REQUIRED = frozenset({"search_ref", "index_version"})
_DOWNSTREAM_CANDIDATE_REQUIRED = frozenset(
    {"case_id", "vector_id", "similarity_score", "index_status"},
)

_EXPECTED_QUERY_METADATA_FIELDS = frozenset(
    {
        "query_hash",
        "model_id",
        "dimension",
        "filters_applied",
        "total_candidates_considered",
        "search_ref",
        "index_version",
    },
)
_EXPECTED_CANDIDATE_FIELDS = frozenset(
    {
        "case_id",
        "vector_id",
        "similarity_score",
        "distance",
        "case_updated_at",
        "input_content_hash",
        "filter_metadata",
        "index_status",
    },
)

_EXPECTED_REQUEST_FIELDS = frozenset(
    {
        "query_text",
        "top_k",
        "filters",
        "include_metadata",
    },
)

_EXPECTED_FILTERS_FIELDS = frozenset(
    {
        "brand_id",
        "store_id",
        "business_type",
        "store_scale",
        "franchise_type",
        "city",
        "city_tier",
        "problem_type",
        "tags",
        "case_status",
        "created_at_from",
        "created_at_to",
        "case_updated_at_from",
        "case_updated_at_to",
    },
)


def _filter_metadata_payload() -> dict[str, object]:
    return {
        "brand_id": "b1",
        "store_id": "s1",
        "business_type": "",
        "store_scale": "",
        "franchise_type": "",
        "city": "",
        "city_tier": "",
        "problem_type": "pt",
        "tags": ["t1"],
        "case_status": "open",
    }


def _candidate_payload() -> dict[str, object]:
    return {
        "case_id": "case_001",
        "vector_id": "vec_001",
        "similarity_score": 0.87,
        "distance": 0.13,
        "case_updated_at": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        "input_content_hash": "qh",
        "filter_metadata": _filter_metadata_payload(),
        "index_status": "searchable",
    }


def _query_metadata_payload() -> dict[str, object]:
    return {
        "query_hash": "a" * 64,
        "model_id": "bge-large-zh",
        "dimension": 1024,
        "filters_applied": {"brand_id": "b1"},
        "total_candidates_considered": 1,
        "search_ref": "a" * 64,
        "index_version": "bge-large-zh@dim1024",
    }


def _response_payload() -> dict[str, object]:
    return {
        "items": [_candidate_payload()],
        "query_metadata": _query_metadata_payload(),
    }


def test_query_metadata_fieldset_includes_downstream_required() -> None:
    """``VectorSearchQueryMetadata`` 字段集与契约快照一致并覆盖下游必填项。"""
    fields = frozenset(VectorSearchQueryMetadata.model_fields)
    assert fields == _EXPECTED_QUERY_METADATA_FIELDS
    assert _DOWNSTREAM_BATCH_REQUIRED.issubset(fields)


def test_candidate_fieldset_includes_downstream_required() -> None:
    """``VectorSearchCandidate`` 字段集与契约快照一致并覆盖下游必填项。"""
    fields = frozenset(VectorSearchCandidate.model_fields)
    assert fields == _EXPECTED_CANDIDATE_FIELDS
    assert _DOWNSTREAM_CANDIDATE_REQUIRED.issubset(fields)


def test_vector_search_request_fieldset_contract() -> None:
    """``VectorSearchRequest`` 字段集白名单与快照一致。"""
    assert frozenset(VectorSearchRequest.model_fields) == _EXPECTED_REQUEST_FIELDS


def test_vector_search_filters_fieldset_contract() -> None:
    """``VectorSearchFilters`` 字段集白名单与快照一致。"""
    assert frozenset(VectorSearchFilters.model_fields) == _EXPECTED_FILTERS_FIELDS


def test_vector_search_filters_rejects_unknown_keys() -> None:
    """过滤对象 ``extra=forbid``：未知键稳定映射为 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        VectorSearchFilters.model_validate({"unknown_filter_key": "x"})


def test_vector_search_request_rejects_unknown_keys() -> None:
    """请求体 ``extra=forbid``：未知键稳定映射为 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        VectorSearchRequest.model_validate(
            {
                "query_text": "q",
                "top_k": 5,
                "random_attr": "x",
            },
        )


def test_index_status_enum_only_allows_searchable() -> None:
    """``VectorSearchIndexStatus`` 枚举仅允许 ``searchable`` 字面量。"""
    assert {member.value for member in VectorSearchIndexStatus} == {"searchable"}


def test_response_serialization_snapshot_keys_stable() -> None:
    """合法响应的 ``model_dump(mode="json")`` keys 与下游必填项保持稳定。"""
    response = VectorSearchResponse.model_validate(_response_payload())
    dumped = response.model_dump(mode="json")

    assert set(dumped.keys()) == {"items", "query_metadata"}

    metadata = dumped["query_metadata"]
    assert set(metadata.keys()) == set(_EXPECTED_QUERY_METADATA_FIELDS)
    assert _DOWNSTREAM_BATCH_REQUIRED.issubset(metadata.keys())
    assert isinstance(metadata["search_ref"], str)
    assert metadata["search_ref"]
    assert isinstance(metadata["index_version"], str)
    assert "@" in metadata["index_version"]

    assert isinstance(dumped["items"], list)
    assert len(dumped["items"]) == 1
    candidate = dumped["items"][0]
    assert set(candidate.keys()) == set(_EXPECTED_CANDIDATE_FIELDS)
    assert _DOWNSTREAM_CANDIDATE_REQUIRED.issubset(candidate.keys())
    assert candidate["index_status"] == "searchable"


def test_similarity_score_is_bounded_float() -> None:
    """``similarity_score`` 为 ``float`` 且语义范围 ``0..1``。"""
    response = VectorSearchResponse.model_validate(_response_payload())
    candidate = response.items[0]
    assert isinstance(candidate.similarity_score, float)
    assert 0.0 <= candidate.similarity_score <= 1.0


def test_response_rejects_when_batch_required_field_missing() -> None:
    """批次缺少下游必填字段时映射为 ``invalid_response``（``ValidationError``）。"""
    for field in _DOWNSTREAM_BATCH_REQUIRED:
        payload = copy.deepcopy(_response_payload())
        metadata = payload["query_metadata"]
        assert isinstance(metadata, dict)
        del metadata[field]
        with pytest.raises(ValidationError):
            VectorSearchResponse.model_validate(payload)


def test_response_rejects_when_candidate_required_field_missing() -> None:
    """任一候选缺少下游必填字段时映射为 ``invalid_response``（``ValidationError``）。"""
    for field in _DOWNSTREAM_CANDIDATE_REQUIRED:
        payload = copy.deepcopy(_response_payload())
        items = payload["items"]
        assert isinstance(items, list)
        candidate = items[0]
        assert isinstance(candidate, dict)
        del candidate[field]
        with pytest.raises(ValidationError):
            VectorSearchResponse.model_validate(payload)


def test_response_rejects_unknown_index_status_literal() -> None:
    """``index_status`` 仅接受字面量集合 ``{"searchable"}``，其他值视为不可解析。"""
    payload = _response_payload()
    items = payload["items"]
    assert isinstance(items, list)
    candidate = items[0]
    assert isinstance(candidate, dict)
    candidate["index_status"] = "unsearchable"
    with pytest.raises(ValidationError):
        VectorSearchResponse.model_validate(payload)
