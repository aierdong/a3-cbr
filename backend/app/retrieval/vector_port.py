"""VectorSearchPort：调用上游 case-vector-indexing 向量搜索能力。

不直接生成案例 embedding 或查询 pgvector，而是调用上游 VectorSearchService
获取问题语义向量候选，映射为推荐候选原语。

强制校验批次级 search_ref 与 index_version，以及候选级 case_id、vector_id、
similarity_score、index_status 最小字段；任一缺失或不可解析按 invalid_response
失败路径处理，不编造候选。

Boundary: VectorSearchPort_
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ErrorCode
from app.retrieval.schemas import NormalizedRetrievalQuery
from app.vector_indexing.schemas import (
    VectorSearchFilters,
    VectorSearchIndexStatus,
    VectorSearchRequest,
    VectorSearchResponse,
)
from app.vector_indexing.search import VectorSearchService


logger = logging.getLogger(__name__)


# =============================================================================
# 依赖契约快照：case-vector-indexing
# =============================================================================
# 必选信封字段：search_ref、index_version
# 必选候选字段：case_id、vector_id、similarity_score、index_status
# =============================================================================


# =============================================================================
# VectorSearchPort 内部 Schema
# =============================================================================


class VectorCandidate(BaseModel):
    """推荐候选原语（内部 Schema）。

    从 case-vector-indexing VectorCandidate 映射而来，保留问题语义相似度、
    距离、索引版本和过滤元数据。
    """

    case_id: str = Field(..., description="案例标识")
    vector_id: str = Field(..., description="向量标识")
    similarity_score: float = Field(..., description="向量相似度分值")
    distance: float = Field(..., description="向量距离")
    case_updated_at: Any = Field(..., description="案例更新时间")
    input_content_hash: str = Field(..., description="输入内容哈希")
    index_status: VectorSearchIndexStatus = Field(
        ..., description="索引状态（固定为 searchable）"
    )
    filter_metadata: dict[str, Any] = Field(
        default_factory=dict, description="过滤元数据"
    )

    model_config = ConfigDict(extra="forbid")


class VectorCandidateBatch(BaseModel):
    """向量候选批次（内部 Schema）。

    必选信封字段：search_ref、index_version
    """

    search_ref: str = Field(..., description="向量搜索运行引用")
    index_version: str = Field(..., description="索引版本标识")
    candidates: list[VectorCandidate] = Field(
        default_factory=list, description="向量候选列表"
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# VectorSearchPort 专用异常
# =============================================================================


class VectorSearchError(Exception):
    """向量搜索基础异常。"""

    error_code: str = ErrorCode.RETRIEVAL_VECTOR_FAILED


class VectorSearchTimeout(VectorSearchError):
    """向量搜索调用超时。"""

    error_code: str = ErrorCode.RETRIEVAL_VECTOR_TIMEOUT


class VectorSearchUnavailable(VectorSearchError):
    """向量搜索服务不可用。"""

    error_code: str = ErrorCode.RETRIEVAL_VECTOR_UNAVAILABLE


class VectorSearchInvalidResponse(VectorSearchError):
    """向量搜索响应无效（字段缺失或不可解析）。"""

    error_code: str = ErrorCode.RETRIEVAL_VECTOR_INVALID_RESPONSE


# =============================================================================
# Feature Flag: 全局启用开关
# =============================================================================
# TODO: 实现完成后设为 True
RETRIEVAL_VECTOR_SEARCH_ENABLED = True


def is_vector_search_enabled() -> bool:
    """检查 VectorSearchPort 功能是否启用。"""
    return RETRIEVAL_VECTOR_SEARCH_ENABLED


# =============================================================================
# VectorSearchPort
# =============================================================================


class VectorSearchPort:
    """向量搜索端口。

    职责：
    1. 调用上游 VectorSearchService，提交标准化查询文本、Top-K 和规范化过滤条件
    2. 校验响应批次级必选字段：search_ref、index_version
    3. 校验候选级必选字段：case_id、vector_id、similarity_score、index_status
    4. 按 index_status 过滤：仅保留 index_status == "searchable" 的候选
    5. 错误语义映射：timeout -> VectorSearchTimeout，unavailable -> VectorSearchUnavailable，
       invalid_response -> VectorSearchInvalidResponse
    6. 记录契约版本信息
    7. 空候选、可检索候选、向量搜索失败三者可稳定区分

    不直接生成案例 embedding 或查询 pgvector。
    """

    def __init__(
        self,
        search_service: VectorSearchService,
    ) -> None:
        """初始化 VectorSearchPort。

        Args:
            search_service: 上游 case-vector-indexing 提供的向量搜索服务。
        """
        self._search_service = search_service

    async def search(
        self,
        query: NormalizedRetrievalQuery,
    ) -> VectorCandidateBatch:
        """执行向量搜索并映射为推荐候选原语。

        Args:
            query: 已标准化的检索查询（包含 normalized_query_text、top_k、applied_filters）。

        Returns:
            VectorCandidateBatch：包含 search_ref、index_version 和可检索候选列表。

        Raises:
            VectorSearchTimeout: 向量搜索超时。
            VectorSearchUnavailable: 向量搜索服务不可用。
            VectorSearchInvalidResponse: 响应字段缺失或不可解析。
        """
        # 1. 构建上游 VectorSearchRequest
        vector_request = VectorSearchRequest(
            query_text=query.normalized_query_text,
            top_k=query.top_k,
            filters=self._build_search_filters(query.applied_filters),
            include_metadata=True,
        )

        # 2. 调用上游向量搜索
        try:
            vector_response: VectorSearchResponse = (
                await self._search_service.search(vector_request)
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

        # 3. 校验批次级必选字段
        meta = vector_response.query_metadata
        if not meta.search_ref or not meta.index_version:
            raise VectorSearchInvalidResponse(
                f"向量搜索响应缺少必选信封字段: "
                f"search_ref={meta.search_ref!r}, index_version={meta.index_version!r}"
            )

        # 4. 校验候选级必选字段并过滤
        raw_candidates: list[dict[str, Any]] = [
            candidate.model_dump() for candidate in vector_response.items
        ]

        validated_candidates: list[VectorCandidate] = []
        for raw in raw_candidates:
            candidate = self._validate_candidate(raw)
            if candidate is None:
                # 候选校验失败，视为 invalid_response
                raise VectorSearchInvalidResponse(
                    f"候选缺少必选字段: case_id={raw.get('case_id')!r}, "
                    f"vector_id={raw.get('vector_id')!r}, "
                    f"similarity_score={raw.get('similarity_score')!r}, "
                    f"index_status={raw.get('index_status')!r}"
                )
            validated_candidates.append(candidate)

        # 5. 按 index_status 过滤：只保留 searchable 候选
        retrievable_candidates = [
            c for c in validated_candidates
            if c.index_status == VectorSearchIndexStatus.SEARCHABLE
        ]

        # 6. 构建并返回 VectorCandidateBatch
        return VectorCandidateBatch(
            search_ref=meta.search_ref,
            index_version=meta.index_version,
            candidates=retrievable_candidates,
        )

    def _build_search_filters(
        self,
        applied_filters: dict[str, Any],
    ) -> VectorSearchFilters:
        """将应用过滤条件映射为上游 VectorSearchFilters。

        Args:
            applied_filters: NormalizedRetrievalQuery.applied_filters。

        Returns:
            VectorSearchFilters：上游向量搜索服务可消费的过滤条件。
        """
        # 只映射 case-vector-indexing 契约支持的字段
        return VectorSearchFilters(
            brand_id=applied_filters.get("brand_id"),
            store_id=applied_filters.get("store_id"),
            problem_type=applied_filters.get("problem_type"),
            tags=applied_filters.get("tags"),
            case_status=applied_filters.get("case_status"),
            created_at_from=applied_filters.get("created_at_from"),
            created_at_to=applied_filters.get("created_at_to"),
        )

    @staticmethod
    def _validate_candidate(raw: dict[str, Any]) -> VectorCandidate | None:
        """校验候选级必选字段。

        必选字段：case_id、vector_id、similarity_score、index_status
        任一缺失或不可解析返回 None。
        """
        case_id = raw.get("case_id")
        vector_id = raw.get("vector_id")
        similarity_score = raw.get("similarity_score")
        index_status = raw.get("index_status")

        # 检查必选字段存在
        if None in (case_id, vector_id, similarity_score, index_status):
            return None

        # 检查必选字段非空字符串（index_status 允许字符串枚举值）
        if not isinstance(case_id, str) or not case_id:
            return None
        if not isinstance(vector_id, str) or not vector_id:
            return None
        if not isinstance(similarity_score, (int, float)):
            return None

        # 校验 index_status 为合法枚举值（兼容字符串和枚举对象）
        if isinstance(index_status, VectorSearchIndexStatus):
            status = index_status
        else:
            try:
                status = VectorSearchIndexStatus(index_status)
            except ValueError:
                return None

        # 过滤元数据
        raw_filter_meta = raw.get("filter_metadata") or {}

        return VectorCandidate(
            case_id=case_id,
            vector_id=vector_id,
            similarity_score=float(similarity_score),
            distance=float(raw.get("distance", 0.0)),
            case_updated_at=raw.get("case_updated_at"),
            input_content_hash=str(raw.get("input_content_hash", "")),
            index_status=status,
            filter_metadata=(
                raw_filter_meta.model_dump()
                if hasattr(raw_filter_meta, "model_dump")
                else raw_filter_meta
            ),
        )

    @staticmethod
    def _map_error(exc: Exception) -> VectorSearchError:
        """将异常映射为 VectorSearchPort 专用异常。

        错误语义映射：
        - timeout -> VectorSearchTimeout
        - unavailable -> VectorSearchUnavailable
        - invalid_response / 字段校验失败 -> VectorSearchInvalidResponse
        - 其他 -> VectorSearchError
        """
        exc_class = VectorSearchError
        error_message = str(exc)

        # 基于异常类型或错误消息推断错误类型
        exc_name = type(exc).__name__.lower()
        error_lower = error_message.lower()

        if "timeout" in exc_name or "timeout" in error_lower:
            exc_class = VectorSearchTimeout
        elif "unavailable" in exc_name or "unavailable" in error_lower or "connection" in exc_name:
            exc_class = VectorSearchUnavailable
        elif "invalid" in exc_name or "validation" in exc_name or "not valid" in error_lower:
            exc_class = VectorSearchInvalidResponse
        elif "rate" in exc_name or "rate" in error_lower or "429" in error_lower:
            # 限流映射为 unavailable
            exc_class = VectorSearchUnavailable
        else:
            # 其他错误默认为 unavailable（供应商失败等）
            exc_class = VectorSearchUnavailable

        return exc_class(error_message)
