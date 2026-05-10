"""EmbeddingInputComposer 单元测试。"""
from datetime import datetime, timezone

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
from app.enrichment.schemas import CaseEnrichmentResultResponse, EnrichmentStatus
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.embedding_input_models import (
    EmbeddingComposeInsufficient,
    EmbeddingComposeNotIndexable,
    EmbeddingInput,
    EmbeddingSegmentKind,
)
from app.vector_indexing.schemas import SourceVersion
from app.vector_indexing.source_models import (
    CaseIndexFilterSnapshot,
    IndexSourceDegradedReason,
    IndexSourceNotIndexableReason,
    IndexSourceSnapshot,
)


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


def _case_base(**kwargs) -> CaseDetailResponse:
    t = kwargs.pop("updated_at", None) or _utc()
    defaults = dict(
        case_id="case_1",
        problem_description="问题描述正文",
        store_id="store_1",
        problem_type=ProblemType.CUSTOMER_COMPLAINT,
        context=ContextSchema(scene="前场排队"),
        root_cause="人工根因叙述",
        solution_steps=[SolutionStepSchema(order=1, content="绝不允许进入向量")],
        outcome=OutcomeSchema(result=OutcomeResult.UNKNOWN, notes="效果也不可进入"),
        status=CaseStatus.ACTIVE,
        created_at=t,
        updated_at=t,
        store=_store(),
    )
    defaults.update(kwargs)
    return CaseDetailResponse(**defaults)


def _filter(tags: list[str] | None = None) -> CaseIndexFilterSnapshot:
    return CaseIndexFilterSnapshot(
        brand_id="brand_1",
        store_id="store_1",
        business_type="火锅",
        store_scale="large",
        franchise_type="直营",
        city="上海",
        city_tier="一线",
        problem_type=ProblemType.CUSTOMER_COMPLAINT.value,
        tags=tags or [],
        case_status=CaseStatus.ACTIVE.value,
    )


def _enrichment(**kwargs) -> CaseEnrichmentResultResponse:
    t = kwargs.pop("case_updated_at", None) or _utc()
    base = dict(
        enrichment_id="enr_1",
        case_id="case_1",
        case_updated_at=t,
        status=EnrichmentStatus.VALID,
        problem_summary="LLM 摘要",
        solution_summary="方案摘要绝不允许出现在拼接文本中",
        structured_suggestions={
            "problem_type_suggestion": "类型建议",
            "root_cause_category": "根因类",
            "applicable_scenarios": ["gamma", "alpha"],
            "confidence_notes": "置信说明也不得进入",
        },
        tag_suggestions=["zebra", "apple"],
        source_references=[],
        missing_information=[],
        output_version="out_v42",
        created_at=t,
        updated_at=t,
    )
    base.update(kwargs)
    return CaseEnrichmentResultResponse.model_validate(base)


@pytest.fixture
def composer() -> EmbeddingInputComposer:
    """返回无状态 EmbeddingInputComposer 实例。"""
    return EmbeddingInputComposer()


def test_not_indexable_when_snapshot_blocked(
    composer: EmbeddingInputComposer,
) -> None:
    """快照标记不可索引时返回 EmbeddingComposeNotIndexable。"""
    snap = IndexSourceSnapshot(
        case_id="c",
        case_detail=_case_base(),
        filter_fields=_filter(),
        case_updated_at=_utc(),
        not_indexable_reason=IndexSourceNotIndexableReason.CASE_DRAFT,
        source_version=SourceVersion(case_updated_at=_utc()),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingComposeNotIndexable)
    assert out.reason == IndexSourceNotIndexableReason.CASE_DRAFT


def test_excludes_solution_outcome_solution_summary_from_concatenated_text(
    composer: EmbeddingInputComposer,
) -> None:
    """拼接文本不包含解法、效果、方案摘要与置信说明等非问题侧片段。"""
    case = _case_base()
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(tags=["apple", "zebra"]),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(
            case_updated_at=case.updated_at,
            enrichment_id=enr.enrichment_id,
            enrichment_status=enr.status.value,
        ),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    forbidden = (
        "绝不允许进入向量",
        "效果也不可进入",
        enr.solution_summary or "",
        "置信说明也不得进入",
    )
    for fragment in forbidden:
        assert fragment not in out.text


def test_stable_section_order_and_join(
    composer: EmbeddingInputComposer,
) -> None:
    """七段顺序固定且全文由非空段按双换行拼接。"""
    case = _case_base()
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    kinds = [s.kind for s in out.sections]
    assert kinds == [
        EmbeddingSegmentKind.PROBLEM_SUMMARY,
        EmbeddingSegmentKind.PROBLEM_DESCRIPTION,
        EmbeddingSegmentKind.PROBLEM_TYPE,
        EmbeddingSegmentKind.CONTEXT,
        EmbeddingSegmentKind.ROOT_CAUSE,
        EmbeddingSegmentKind.APPLICABLE_SCENARIOS,
        EmbeddingSegmentKind.TAGS,
    ]
    non_empty = [s.text for s in out.sections if s.text.strip()]
    assert out.text == "\n\n".join(non_empty)


def test_same_snapshot_deterministic_text(
    composer: EmbeddingInputComposer,
) -> None:
    """相同快照生成一致全文与各段 model_dump。"""
    case = _case_base()
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    a = composer.compose_case_input(snap)
    b = composer.compose_case_input(snap.model_copy(deep=True))
    assert isinstance(a, EmbeddingInput)
    assert isinstance(b, EmbeddingInput)
    assert a.text == b.text
    assert [s.model_dump() for s in a.sections] == [
        s.model_dump() for s in b.sections
    ]


def test_tags_and_scenarios_sorted_lexicographically(
    composer: EmbeddingInputComposer,
) -> None:
    """标签与适用场景按字典序展开为稳定文本。"""
    case = _case_base()
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    tags_sec = next(s for s in out.sections if s.kind == EmbeddingSegmentKind.TAGS)
    scen_sec = next(
        s for s in out.sections if s.kind == EmbeddingSegmentKind.APPLICABLE_SCENARIOS
    )
    assert tags_sec.text == "apple, zebra"
    assert scen_sec.text == "alpha, gamma"


def test_problem_type_merges_case_enum_and_llm_suggestion(
    composer: EmbeddingInputComposer,
) -> None:
    """问题类型段合并案例枚举与 LLM 建议文本。"""
    case = _case_base(problem_type=ProblemType.OPERATIONS)
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    pt = next(s for s in out.sections if s.kind == EmbeddingSegmentKind.PROBLEM_TYPE)
    assert ProblemType.OPERATIONS.value in pt.text
    assert "类型建议" in pt.text


def test_root_cause_merges_structured_and_case_narrative(
    composer: EmbeddingInputComposer,
) -> None:
    """根因段合并结构化分类与人工 root_cause 叙述。"""
    case = _case_base(root_cause="门店流程")
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    rc = next(s for s in out.sections if s.kind == EmbeddingSegmentKind.ROOT_CAUSE)
    assert "根因类" in rc.text
    assert "门店流程" in rc.text


def test_context_json_stable_serialization(
    composer: EmbeddingInputComposer,
) -> None:
    """场景上下文以 sort_keys 的稳定 JSON 序列化输出。"""
    ctx = ContextSchema.model_validate({"scene": "z", "extra_field": "a"})
    case = _case_base(context=ctx)
    enr = _enrichment()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    ctx = next(s for s in out.sections if s.kind == EmbeddingSegmentKind.CONTEXT)
    assert ctx.text == '{"extra_field":"a","scene":"z"}'


def test_sources_carry_output_version_for_llm_segments(
    composer: EmbeddingInputComposer,
) -> None:
    """LLM 来源段落携带 output_version 作为 version_token。"""
    case = _case_base()
    enr = _enrichment(output_version="ver_xyz")
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    summary = out.sections[0]
    assert summary.sources
    assert any(r.version_token == "ver_xyz" for r in summary.sources)


def test_sources_carry_case_updated_at_for_case_only_segments(
    composer: EmbeddingInputComposer,
) -> None:
    """纯案例字段段落携带案例 updated_at ISO 版本锚。"""
    case = _case_base()
    enr = _enrichment()
    iso = case.updated_at.isoformat()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    desc = out.sections[1]
    assert desc.sources
    assert any(r.version_token == iso for r in desc.sources)


def test_degraded_missing_enrichment_composes_minimal_and_sets_reason(
    composer: EmbeddingInputComposer,
) -> None:
    """无 VALID enrichment 时降级组合并保留 degraded_reason。"""
    case = _case_base()
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(tags=[]),
        case_updated_at=case.updated_at,
        enrichment_consumable=None,
        degraded_reason=IndexSourceDegradedReason.ENRICHMENT_MISSING,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingInput)
    assert out.degraded_reason == IndexSourceDegradedReason.ENRICHMENT_MISSING
    summary = next(
        s for s in out.sections if s.kind == EmbeddingSegmentKind.PROBLEM_SUMMARY
    )
    scen = next(
        s
        for s in out.sections
        if s.kind == EmbeddingSegmentKind.APPLICABLE_SCENARIOS
    )
    tags = next(s for s in out.sections if s.kind == EmbeddingSegmentKind.TAGS)
    assert summary.text == ""
    assert scen.text == ""
    assert tags.text == ""
    assert "问题描述正文" in out.text
    assert ProblemType.CUSTOMER_COMPLAINT.value in out.text


def test_insufficient_when_problem_description_blank(
    composer: EmbeddingInputComposer,
) -> None:
    """问题描述空白时返回 EmbeddingComposeInsufficient 并列出缺失字段。"""
    case = _case_base(problem_description="   ")
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=None,
        degraded_reason=IndexSourceDegradedReason.ENRICHMENT_MISSING,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingComposeInsufficient)
    assert "A3Case.problem_description" in out.missing_fields


def test_compose_query_input_single_segment(
    composer: EmbeddingInputComposer,
) -> None:
    """查询路径仅生成单段 trimmed query_text。"""
    out = composer.compose_query_input("  用户问题  ")
    assert isinstance(out, EmbeddingInput)
    assert out.text == "用户问题"
    assert len(out.sections) == 1
    assert out.sections[0].text == "用户问题"
    assert out.degraded_reason is None


def test_compose_query_input_empty_raises(
    composer: EmbeddingInputComposer,
) -> None:
    """空查询文本抛出 ValueError。"""
    with pytest.raises(ValueError, match="query_text"):
        composer.compose_query_input("   ")


def test_insufficient_when_structured_suggestions_invalid(
    composer: EmbeddingInputComposer,
) -> None:
    """structured_suggestions 无法校验为 StructuredSuggestions 时返回不足。"""
    case = _case_base()
    enr = _enrichment(
        structured_suggestions={
            "problem_type_suggestion": "",
            "root_cause_category": "x",
            "applicable_scenarios": [],
        },
    )
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=case.updated_at,
        enrichment_consumable=enr,
        source_version=SourceVersion(case_updated_at=case.updated_at),
    )
    out = composer.compose_case_input(snap)
    assert isinstance(out, EmbeddingComposeInsufficient)
    assert any(
        "structured_suggestions" in f or "CaseEnrichmentResult" in f
        for f in out.missing_fields
    )
