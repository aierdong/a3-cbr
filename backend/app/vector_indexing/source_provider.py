"""案例索引上游数据源提供者（读取 CaseService + EnrichmentRepository）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cases.schemas import CaseDetailResponse, CaseStatus
from app.cases.service import CaseNotFoundError, CaseService
from app.enrichment.models import CaseEnrichmentResult as CaseEnrichmentResultRow
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import CaseEnrichmentResultResponse, EnrichmentStatus
from app.vector_indexing.schemas import SourceVersion
from app.vector_indexing.source_models import (
    CaseIndexFilterSnapshot,
    IndexSourceDegradedReason,
    IndexSourceNotIndexableReason,
    IndexSourceSnapshot,
)


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            tag = item.get("tag")
            if isinstance(tag, str) and tag:
                out.append(tag)
    return out


def _filter_snapshot_from_case(
    case: CaseDetailResponse,
    tags: list[str],
) -> CaseIndexFilterSnapshot:
    st = case.store
    return CaseIndexFilterSnapshot(
        brand_id=st.brand_id,
        store_id=st.store_id,
        business_type=st.business_type,
        store_scale=st.store_scale,
        franchise_type=st.franchise_type,
        city=st.city,
        city_tier=st.city_tier,
        problem_type=case.problem_type.value,
        tags=tags,
        case_status=case.status.value,
    )


def _row_to_enrichment_response(row: CaseEnrichmentResultRow) -> CaseEnrichmentResultResponse:
    return CaseEnrichmentResultResponse.model_validate(
        {
            "enrichment_id": row.enrichment_id,
            "case_id": row.case_id,
            "case_updated_at": row.case_updated_at,
            "status": row.status,
            "problem_summary": row.problem_summary,
            "solution_summary": row.solution_summary,
            "structured_suggestions": row.structured_suggestions,
            "tag_suggestions": _normalize_tags(row.tag_suggestions),
            "source_references": row.source_references,
            "missing_information": [],
            "output_version": row.output_version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        },
    )


def _build_source_version(
    case_updated_at: datetime,
    row: CaseEnrichmentResultRow | None,
) -> SourceVersion:
    if row is None:
        return SourceVersion(
            case_updated_at=case_updated_at,
            enrichment_id=None,
            enrichment_status=None,
        )
    return SourceVersion(
        case_updated_at=case_updated_at,
        enrichment_id=row.enrichment_id,
        enrichment_status=str(row.status),
    )


class CaseIndexSourceProvider:
    """从案例管理与 LLM 派生层组装向量索引输入快照（只读）。"""

    def __init__(
        self,
        case_service: CaseService,
        enrichment_repository: EnrichmentRepository,
    ) -> None:
        """初始化索引上游提供者。

        Args:
            case_service: 案例业务服务。
            enrichment_repository: LLM 派生结果仓储（只读访问）。
        """
        self._cases = case_service
        self._enrichment = enrichment_repository

    async def load_source(self, case_id: str) -> IndexSourceSnapshot:
        """加载指定案例的索引上游快照。

        Args:
            case_id: 案例标识。

        Returns:
            索引快照：含过滤镜像、来源版本及降级/不可索引原因。
        """
        try:
            case = await self._cases.get_case(case_id)
        except CaseNotFoundError:
            return IndexSourceSnapshot(
                case_id=case_id,
                not_indexable_reason=IndexSourceNotIndexableReason.CASE_DELETED,
                degraded_detail="案例不存在或已删除",
            )

        row = await self._enrichment.get_enrichment_result_for_case(case_id)
        tags = (
            _normalize_tags(row.tag_suggestions)
            if row is not None and row.status == EnrichmentStatus.VALID
            else []
        )
        filt = _filter_snapshot_from_case(case, tags)
        version = _build_source_version(case.updated_at, row)

        if case.status == CaseStatus.DRAFT:
            return IndexSourceSnapshot(
                case_id=case_id,
                case_detail=case,
                filter_fields=filt,
                case_updated_at=case.updated_at,
                enrichment_consumable=(
                    _row_to_enrichment_response(row)
                    if row is not None and row.status == EnrichmentStatus.VALID
                    else None
                ),
                source_version=version,
                not_indexable_reason=IndexSourceNotIndexableReason.CASE_DRAFT,
                degraded_detail=None,
            )

        if case.status == CaseStatus.ARCHIVED:
            return IndexSourceSnapshot(
                case_id=case_id,
                case_detail=case,
                filter_fields=filt,
                case_updated_at=case.updated_at,
                enrichment_consumable=(
                    _row_to_enrichment_response(row)
                    if row is not None and row.status == EnrichmentStatus.VALID
                    else None
                ),
                source_version=version,
                not_indexable_reason=IndexSourceNotIndexableReason.CASE_ARCHIVED,
                degraded_detail=None,
            )

        consumable = (
            _row_to_enrichment_response(row)
            if row is not None and row.status == EnrichmentStatus.VALID
            else None
        )

        if row is None:
            return IndexSourceSnapshot(
                case_id=case_id,
                case_detail=case,
                filter_fields=filt,
                case_updated_at=case.updated_at,
                enrichment_consumable=None,
                source_version=version,
                degraded_reason=IndexSourceDegradedReason.ENRICHMENT_MISSING,
                degraded_detail="无 LLM 派生结果记录",
            )

        if row.status != EnrichmentStatus.VALID:
            return IndexSourceSnapshot(
                case_id=case_id,
                case_detail=case,
                filter_fields=filt,
                case_updated_at=case.updated_at,
                enrichment_consumable=None,
                source_version=version,
                degraded_reason=IndexSourceDegradedReason.ENRICHMENT_FAILED,
                degraded_detail="派生结果未通过校验（status=failed）",
            )

        return IndexSourceSnapshot(
            case_id=case_id,
            case_detail=case,
            filter_fields=filt,
            case_updated_at=case.updated_at,
            enrichment_consumable=consumable,
            source_version=version,
        )
