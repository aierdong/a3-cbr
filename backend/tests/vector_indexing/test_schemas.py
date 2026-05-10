"""向量索引 API schema 与枚举契约测试。

对齐 docs/contracts/case-vector-indexing.openapi.yaml；
删除请求/响应对齐 design.md「DeleteVectorIndexRequest/Response」。
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.core.errors import ErrorCode


class TestErrorCodeVectorIndexing:
    """稳定错误码存在于共享 ErrorCode。"""

    def test_vector_and_embedding_error_codes_defined(self):
        """向量索引与 embedding 错误码均已挂载到 ErrorCode。"""
        assert ErrorCode.VECTOR_JOB_NOT_FOUND == "VECTOR_JOB_NOT_FOUND"
        assert ErrorCode.VECTOR_STATE_CONFLICT == "VECTOR_STATE_CONFLICT"
        assert ErrorCode.VECTOR_CONFLICT == "VECTOR_CONFLICT"
        assert ErrorCode.VECTOR_RETRY_NOT_ALLOWED == "VECTOR_RETRY_NOT_ALLOWED"
        assert ErrorCode.VECTOR_INPUT_INSUFFICIENT == "VECTOR_INPUT_INSUFFICIENT"
        assert ErrorCode.VECTOR_CASE_NOT_INDEXABLE == "VECTOR_CASE_NOT_INDEXABLE"
        assert ErrorCode.VECTOR_PGVECTOR_UNAVAILABLE == "VECTOR_PGVECTOR_UNAVAILABLE"
        assert ErrorCode.EMBEDDING_TIMEOUT == "EMBEDDING_TIMEOUT"
        assert ErrorCode.EMBEDDING_RATE_LIMITED == "EMBEDDING_RATE_LIMITED"
        assert ErrorCode.EMBEDDING_PROVIDER_ERROR == "EMBEDDING_PROVIDER_ERROR"
        assert ErrorCode.EMBEDDING_INVALID_RESPONSE == "EMBEDDING_INVALID_RESPONSE"
        assert ErrorCode.EMBEDDING_DIMENSION_MISMATCH == "EMBEDDING_DIMENSION_MISMATCH"
        assert ErrorCode.EMBEDDING_CONFIG_MISSING == "EMBEDDING_CONFIG_MISSING"


class TestRefreshVectorIndexRequest:
    """RefreshVectorIndexRequest 校验。"""

    def test_accepts_extra_properties(self):
        """允许附加字段以便契约演进。"""
        from app.vector_indexing.schemas import RefreshVectorIndexRequest

        m = RefreshVectorIndexRequest.model_validate(
            {"force_rebuild": True, "requested_by": "admin", "future_flag": 1}
        )
        assert m.force_rebuild is True
        assert m.requested_by == "admin"


class TestDeleteVectorIndexRequest:
    """DeleteVectorIndexRequest 校验。"""

    def test_requires_case_id_or_vector_id(self):
        """case_id 与 vector_id 均未提供时应拒绝。"""
        from app.vector_indexing.schemas import DeleteVectorIndexRequest, DeleteVectorIndexReason

        with pytest.raises(ValidationError):
            DeleteVectorIndexRequest(
                reason=DeleteVectorIndexReason.CASE_DELETED,
                requested_by="system",
            )

    def test_valid_with_case_id(self):
        """仅提供 case_id 时应通过。"""
        from app.vector_indexing.schemas import DeleteVectorIndexRequest, DeleteVectorIndexReason

        req = DeleteVectorIndexRequest(
            case_id="c1",
            reason=DeleteVectorIndexReason.CASE_DELETED,
            requested_by="system",
        )
        assert req.case_id == "c1"
        assert req.vector_id is None


class TestVectorSearchRequest:
    """VectorSearchRequest 校验。"""

    def test_rejects_empty_query_text(self):
        """query_text 为空应拒绝。"""
        from app.vector_indexing.schemas import VectorSearchRequest

        with pytest.raises(ValidationError):
            VectorSearchRequest(query_text="", top_k=10)

    def test_top_k_bounds(self):
        """top_k 须在 [1, 100] 内。"""
        from app.vector_indexing.schemas import VectorSearchRequest

        with pytest.raises(ValidationError):
            VectorSearchRequest(query_text="x", top_k=0)
        with pytest.raises(ValidationError):
            VectorSearchRequest(query_text="x", top_k=101)

    def test_default_top_k(self):
        """默认 top_k 与契约默认一致。"""
        from app.vector_indexing.schemas import VectorSearchRequest

        m = VectorSearchRequest(query_text="hello")
        assert m.top_k == 20


class TestVectorEnums:
    """API 枚举取值。"""

    def test_job_status_values_match_openapi(self):
        """任务状态集合与 OpenAPI一致。"""
        from app.vector_indexing.schemas import VectorJobStatus

        values = {e.value for e in VectorJobStatus}
        assert values == {
            "queued",
            "running",
            "succeeded",
            "failed",
            "retryable",
            "cancelled",
        }

    def test_index_status_includes_published_and_degraded(self):
        """聚合状态包含 published / degraded / unsearchable。"""
        from app.vector_indexing.schemas import VectorIndexStatus

        names = {e.value for e in VectorIndexStatus}
        assert {"published", "degraded", "unsearchable"}.issubset(names)


class TestVectorSearchResponseRoundTrip:
    """搜索响应序列化往返。"""

    def test_minimal_response(self):
        """最小合法候选与元数据可 JSON 往返。"""
        from app.vector_indexing.schemas import (
            VectorCandidateFilterMetadata,
            VectorSearchCandidate,
            VectorSearchIndexStatus,
            VectorSearchQueryMetadata,
            VectorSearchResponse,
        )

        now = datetime.now(timezone.utc)
        candidate = VectorSearchCandidate(
            case_id="case1",
            vector_id="vec1",
            similarity_score=0.9,
            distance=0.1,
            case_updated_at=now,
            input_content_hash="abc",
            filter_metadata=VectorCandidateFilterMetadata(
                brand_id="b",
                store_id="s",
                business_type="bt",
                store_scale="ss",
                franchise_type="ft",
                city="c",
                city_tier="t1",
                problem_type="pt",
                tags=["a"],
                case_status="active",
            ),
            index_status=VectorSearchIndexStatus.SEARCHABLE,
        )
        meta = VectorSearchQueryMetadata(
            query_hash="qh",
            model_id="bge-large-zh",
            dimension=1024,
            filters_applied={},
            search_ref="qh",
            index_version="bge-large-zh@dim1024",
        )
        resp = VectorSearchResponse(items=[candidate], query_metadata=meta)
        dumped = resp.model_dump(mode="json")
        restored = VectorSearchResponse.model_validate(dumped)
        assert restored.items[0].case_id == "case1"
