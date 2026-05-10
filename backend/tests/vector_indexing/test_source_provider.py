"""CaseIndexSourceProvider 单元测试（mock CaseService / EnrichmentRepository）。"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cases.schemas import (
    CaseDetailResponse,
    CaseStatus,
    ContextSchema,
    OutcomeResult,
    OutcomeSchema,
    ProblemType,
    SolutionStepSchema,
    StoreInfoSummary,
)
from app.cases.service import CaseNotFoundError
from app.enrichment.models import CaseEnrichmentResult as EnrichmentRow
from app.enrichment.schemas import EnrichmentStatus
from app.vector_indexing.source_models import (
    IndexSourceDegradedReason,
    IndexSourceNotIndexableReason,
)
from app.vector_indexing.source_provider import CaseIndexSourceProvider


def _utc() -> datetime:
    return datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _store() -> StoreInfoSummary:
    return StoreInfoSummary(
        store_id="store_1",
        store_name="门店",
        brand_id="brand_1",
        brand_name="品牌",
        business_type="火锅",
        store_scale="large",
        franchise_type="直营",
        city="上海",
        city_tier="一线",
        updated_at=_utc(),
    )


def _active_case(
    case_id: str = "case_1",
    updated_at: datetime | None = None,
) -> CaseDetailResponse:
    t = updated_at or _utc()
    return CaseDetailResponse(
        case_id=case_id,
        problem_description="问题描述文本",
        store_id="store_1",
        problem_type=ProblemType.CUSTOMER_COMPLAINT,
        context=ContextSchema(scene="前场排队"),
        root_cause="根因说明",
        solution_steps=[SolutionStepSchema(order=1, content="步骤")],
        outcome=OutcomeSchema(result=OutcomeResult.UNKNOWN, notes=""),
        status=CaseStatus.ACTIVE,
        created_at=t,
        updated_at=t,
        store=_store(),
    )


def _enrichment_row(
    *,
    status: str = EnrichmentStatus.VALID,
    case_id: str = "case_1",
    case_updated_at: datetime | None = None,
) -> EnrichmentRow:
    t = case_updated_at or _utc()
    return EnrichmentRow(
        enrichment_id="enr_1",
        case_id=case_id,
        case_updated_at=t,
        status=status,
        problem_summary="摘要",
        solution_summary=None,
        structured_suggestions={
            "problem_type_suggestion": "类型建议",
            "root_cause_category": "根因类",
            "applicable_scenarios": ["场景一"],
            "confidence_notes": "",
        },
        tag_suggestions=["标签a"],
        source_references=["problem_description"],
        output_version="v1",
        created_at=t,
        updated_at=t,
    )


@pytest.fixture
def case_service() -> MagicMock:
    """案例服务 MagicMock。"""
    return MagicMock()


@pytest.fixture
def enrichment_repo() -> MagicMock:
    """增强仓储 MagicMock。"""
    return MagicMock()


@pytest.fixture
def provider(
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> CaseIndexSourceProvider:
    """装配 CaseIndexSourceProvider。"""
    return CaseIndexSourceProvider(case_service, enrichment_repo)


async def test_deleted_case_not_indexable(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
) -> None:
    """删除案例映射为 CASE_DELETED，且无来源版本。"""
    case_service.get_case = AsyncMock(side_effect=CaseNotFoundError("missing"))

    snap = await provider.load_source("missing")

    assert snap.case_id == "missing"
    assert snap.case_detail is None
    assert snap.not_indexable_reason == IndexSourceNotIndexableReason.CASE_DELETED
    assert snap.source_version is None


async def test_draft_case_not_indexable(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """草稿案例返回 CASE_DRAFT 不可索引原因。"""
    case = _active_case()
    draft_case = case.model_copy(update={"status": CaseStatus.DRAFT})
    case_service.get_case = AsyncMock(return_value=draft_case)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=None)

    snap = await provider.load_source(case.case_id)

    assert snap.not_indexable_reason == IndexSourceNotIndexableReason.CASE_DRAFT
    assert snap.case_detail is not None
    assert snap.filter_fields.case_status == CaseStatus.DRAFT.value


async def test_archived_case_not_indexable(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """归档案例返回 CASE_ARCHIVED。"""
    case = _active_case()
    archived = case.model_copy(update={"status": CaseStatus.ARCHIVED})
    case_service.get_case = AsyncMock(return_value=archived)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=None)

    snap = await provider.load_source(case.case_id)

    assert snap.not_indexable_reason == IndexSourceNotIndexableReason.CASE_ARCHIVED


async def test_active_missing_enrichment_degraded(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """激活案例无派生行时应给出 ENRICHMENT_MISSING 降级原因。"""
    case = _active_case()
    case_service.get_case = AsyncMock(return_value=case)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=None)

    snap = await provider.load_source(case.case_id)

    assert snap.degraded_reason == IndexSourceDegradedReason.ENRICHMENT_MISSING
    assert snap.enrichment_consumable is None
    assert snap.source_version is not None
    assert snap.source_version.case_updated_at == case.updated_at
    assert snap.source_version.enrichment_id is None


async def test_active_failed_enrichment_degraded(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """failed 派生行应给出 ENRICHMENT_FAILED 并在来源版本中保留 enrichment_id。"""
    case = _active_case()
    row = _enrichment_row(status=EnrichmentStatus.FAILED)
    case_service.get_case = AsyncMock(return_value=case)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=row)

    snap = await provider.load_source(case.case_id)

    assert snap.degraded_reason == IndexSourceDegradedReason.ENRICHMENT_FAILED
    assert snap.enrichment_consumable is None
    assert snap.source_version.enrichment_id == row.enrichment_id
    assert snap.source_version.enrichment_status == EnrichmentStatus.FAILED.value


async def test_active_valid_enrichment_snapshot(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """VALID 派生结果应写入 consumable 并填充 SourceVersion。"""
    case = _active_case()
    row = _enrichment_row()
    case_service.get_case = AsyncMock(return_value=case)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=row)

    snap = await provider.load_source(case.case_id)

    assert snap.not_indexable_reason is None
    assert snap.degraded_reason is None
    assert snap.enrichment_consumable is not None
    assert snap.enrichment_consumable.enrichment_id == row.enrichment_id
    assert snap.filter_fields.tags == ["标签a"]
    assert snap.source_version.enrichment_id == row.enrichment_id
    assert snap.source_version.enrichment_status == EnrichmentStatus.VALID.value


async def test_same_case_id_stable_source_version_when_no_enrichment(
    provider: CaseIndexSourceProvider,
    case_service: MagicMock,
    enrichment_repo: MagicMock,
) -> None:
    """同一案例多次读取在无派生行时来源版本一致。"""
    case = _active_case(case_id="case_stable")
    case_service.get_case = AsyncMock(return_value=case)
    enrichment_repo.get_enrichment_result_for_case = AsyncMock(return_value=None)

    first = await provider.load_source("case_stable")
    second = await provider.load_source("case_stable")

    assert first.source_version == second.source_version
    assert first.case_id == second.case_id == "case_stable"
