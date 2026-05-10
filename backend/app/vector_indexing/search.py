"""向量搜索：查询校验、查询向量生成、仓储 Top-K 检索与响应映射。"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from app.core.errors import ErrorCode
from app.vector_indexing.embedding_client import EmbeddingClient
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.repository_types import VectorCandidateRecord, VectorSearchQuery
from app.vector_indexing.schemas import (
    EmbeddingRequest,
    EmbeddingResult,
    VectorCandidateFilterMetadata,
    VectorSearchCandidate,
    VectorSearchFilters,
    VectorSearchQueryMetadata,
    VectorSearchRequest,
    VectorSearchResponse,
)

if TYPE_CHECKING:
    from app.vector_indexing.repository import VectorRepository

logger = logging.getLogger(__name__)


class VectorSearchValidationError(Exception):
    """搜索请求语义校验失败（字段级）。"""

    def __init__(
        self,
        field: str,
        message: str,
        *,
        error_code: str = ErrorCode.VALIDATION_ERROR,
    ) -> None:
        """构造字段级校验异常。"""
        self.field = field
        self.message = message
        self.error_code = error_code
        super().__init__(message)


def _validate_filters(filters: VectorSearchFilters | None) -> None:
    if filters is None:
        return
    if filters.tags is not None:
        for tag in filters.tags:
            if not isinstance(tag, str) or not tag.strip():
                raise VectorSearchValidationError(
                    "filters.tags",
                    "标签列表不得包含空字符串",
                )
    if (
        filters.created_at_from is not None
        and filters.created_at_to is not None
        and filters.created_at_from > filters.created_at_to
    ):
        raise VectorSearchValidationError(
            "filters.created_at",
            "created_at_from 不得晚于 created_at_to",
        )
    if (
        filters.case_updated_at_from is not None
        and filters.case_updated_at_to is not None
        and filters.case_updated_at_from > filters.case_updated_at_to
    ):
        raise VectorSearchValidationError(
            "filters.case_updated_at",
            "case_updated_at_from 不得晚于 case_updated_at_to",
        )


def _validate_request_semantics(request: VectorSearchRequest) -> None:
    if not request.query_text.strip():
        raise VectorSearchValidationError("query_text", "查询文本不能为空")
    _validate_filters(request.filters)


def _filters_applied(request: VectorSearchRequest) -> dict[str, Any]:
    if request.filters is None:
        return {}
    return request.filters.model_dump(mode="json", exclude_none=True)


def _repository_search_query(
    request: VectorSearchRequest,
    query_embedding: list[float],
) -> VectorSearchQuery:
    """由搜索请求与查询向量构造仓储检索参数。"""
    f: VectorSearchFilters | None = request.filters
    return VectorSearchQuery(
        query_embedding=query_embedding,
        top_k=request.top_k,
        brand_id=f.brand_id if f else None,
        store_id=f.store_id if f else None,
        problem_type=f.problem_type if f else None,
        tags=f.tags if f else None,
        case_status=f.case_status if f else None,
        case_updated_at_from=f.case_updated_at_from if f else None,
        case_updated_at_to=f.case_updated_at_to if f else None,
    )


def _candidate_record_to_api(record: VectorCandidateRecord) -> VectorSearchCandidate:
    """仓储候选记录 → API 契约 ``VectorSearchCandidate``。"""
    fm = record.filter_metadata
    return VectorSearchCandidate(
        case_id=record.case_id,
        vector_id=record.vector_id,
        similarity_score=1.0 - record.distance,
        distance=record.distance,
        case_updated_at=record.case_updated_at,
        input_content_hash=record.input_content_hash,
        filter_metadata=VectorCandidateFilterMetadata(
            brand_id=fm.brand_id,
            store_id=fm.store_id,
            business_type=fm.business_type,
            store_scale=fm.store_scale,
            franchise_type=fm.franchise_type,
            city=fm.city,
            city_tier=fm.city_tier,
            problem_type=fm.problem_type,
            tags=fm.tags,
            case_status=fm.case_status,
        ),
    )


class VectorSearchService:
    """查询向量生成与带结构化过滤的 Top-K 语义候选检索。"""

    def __init__(
        self,
        composer: EmbeddingInputComposer,
        embedding_client: EmbeddingClient,
        *,
        repository: VectorRepository | None = None,
    ) -> None:
        """初始化搜索服务。

        Args:
            composer: 查询文本组合器。
            embedding_client: 搜索路径嵌入客户端（``embed_for_query``）。
            repository: 向量仓储；``search`` 依赖其 ``search`` 原语。

        Returns:
            None
        """
        self._composer = composer
        self._embedding_client = embedding_client
        self._repository = repository

    async def build_query_vector(
        self,
        request: VectorSearchRequest,
    ) -> tuple[EmbeddingResult, VectorSearchQueryMetadata]:
        """校验请求并生成查询向量与查询元数据。

        Args:
            request: 向量搜索请求。

        Returns:
            嵌入结果与 ``VectorSearchQueryMetadata``。

        Raises:
            VectorSearchValidationError: 语义校验失败。
            LLMClientError: 嵌入调用失败（不重试、不吞错）。
        """
        _validate_request_semantics(request)
        composed = self._composer.compose_query_input(request.query_text)
        query_hash = hashlib.sha256(composed.text.encode("utf-8")).hexdigest()
        filters_applied = _filters_applied(request)

        emb_req = EmbeddingRequest(
            text=composed.text,
            content_fingerprint=query_hash,
        )
        embedding_result = await self._embedding_client.embed_for_query(emb_req)

        logger.info(
            "vector_search_query_embedding_ok",
            extra={
                "query_hash": query_hash,
                "model_id": embedding_result.embedding_model_id,
                "dimension": embedding_result.embedding_dimension,
            },
        )

        meta = VectorSearchQueryMetadata(
            query_hash=query_hash,
            model_id=embedding_result.embedding_model_id,
            dimension=embedding_result.embedding_dimension,
            filters_applied=filters_applied,
            total_candidates_considered=None,
        )
        return embedding_result, meta

    async def search(self, request: VectorSearchRequest) -> VectorSearchResponse:
        """校验并嵌入查询向量，调用仓储 Top-K 检索并映射候选列表。

        Args:
            request: 向量搜索请求。

        Returns:
            按向量距离升序的候选列表与查询元数据（不做加权或重排）。

        Raises:
            VectorSearchValidationError: 语义校验失败。
            LLMClientError: 嵌入调用失败。
            RuntimeError: 未注入 ``VectorRepository``。
        """
        embedding_result, meta = await self.build_query_vector(request)
        if self._repository is None:
            raise RuntimeError("VectorSearchService.search requires an injected VectorRepository")
        query = _repository_search_query(request, embedding_result.vector)
        records = await self._repository.search(query)
        meta.total_candidates_considered = len(records)
        items = [_candidate_record_to_api(r) for r in records]
        return VectorSearchResponse(items=items, query_metadata=meta)
