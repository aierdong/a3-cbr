"""问题侧 embedding 输入文本组合（EmbeddingInputComposer）。"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.cases.schemas import CaseDetailResponse
from app.enrichment.schemas import CaseEnrichmentResultResponse, StructuredSuggestions
from app.vector_indexing.embedding_input_models import (
    ComposeCaseInputResult,
    EmbeddingComposeInsufficient,
    EmbeddingComposeNotIndexable,
    EmbeddingInput,
    EmbeddingInputSection,
    EmbeddingSegmentKind,
    EmbeddingSourceRef,
)
from app.vector_indexing.source_models import (
    IndexSourceDegradedReason,
    IndexSourceSnapshot,
)


def serialize_context_for_embedding(context_dump: dict) -> str:
    """将场景上下文稳定序列化为单行 JSON 字符串。

    规则（与设计一致）：``json.dumps(..., sort_keys=True, separators=(',', ':'),
    ensure_ascii=False)``；不在末尾追加换行；嵌套 dict/list 由 JSON 标准决定，
    不在此处插入额外空格或换行。

    Args:
        context_dump: ``ContextSchema.model_dump(mode="json")`` 得到的可 JSON 化 dict。

    Returns:
        单行 JSON 文本。
    """
    return json.dumps(
        context_dump,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _assemble_case_embedding_sections(
    case: CaseDetailResponse,
    desc: str,
    case_ver: str,
    consumable: CaseEnrichmentResultResponse | None,
    structured: StructuredSuggestions | None,
    enrich_ver: str | None,
) -> list[EmbeddingInputSection]:
    sections: list[EmbeddingInputSection] = []

    summary_text = ""
    summary_sources: list[EmbeddingSourceRef] = []
    if consumable is not None and consumable.problem_summary:
        summary_text = consumable.problem_summary.strip()
        if summary_text and enrich_ver:
            summary_sources = [
                EmbeddingSourceRef(
                    field_path="CaseEnrichmentResult.problem_summary",
                    version_token=enrich_ver,
                ),
            ]
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.PROBLEM_SUMMARY,
            text=summary_text,
            sources=summary_sources,
        ),
    )

    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.PROBLEM_DESCRIPTION,
            text=desc,
            sources=[
                EmbeddingSourceRef(
                    field_path="A3Case.problem_description",
                    version_token=case_ver,
                ),
            ],
        ),
    )

    pt_parts: list[str] = [case.problem_type.value]
    if structured is not None:
        sug = structured.problem_type_suggestion.strip()
        if sug:
            pt_parts.append(sug)
    pt_text = " ".join(pt_parts)
    pt_sources = [
        EmbeddingSourceRef(
            field_path="A3Case.problem_type",
            version_token=case_ver,
        ),
    ]
    if structured is not None and enrich_ver:
        pt_sources.append(
            EmbeddingSourceRef(
                field_path=(
                    "CaseEnrichmentResult."
                    "structured_suggestions.problem_type_suggestion"
                ),
                version_token=enrich_ver,
            ),
        )
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.PROBLEM_TYPE,
            text=pt_text,
            sources=pt_sources,
        ),
    )

    ctx_text = serialize_context_for_embedding(case.context.model_dump(mode="json"))
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.CONTEXT,
            text=ctx_text,
            sources=[
                EmbeddingSourceRef(
                    field_path="A3Case.context",
                    version_token=case_ver,
                ),
            ],
        ),
    )

    rc_parts: list[str] = []
    rc_sources: list[EmbeddingSourceRef] = []
    if structured is not None:
        rc_cat = structured.root_cause_category.strip()
        if rc_cat:
            rc_parts.append(rc_cat)
            if enrich_ver:
                rc_sources.append(
                    EmbeddingSourceRef(
                        field_path=(
                            "CaseEnrichmentResult."
                            "structured_suggestions.root_cause_category"
                        ),
                        version_token=enrich_ver,
                    ),
                )
    narrative = case.root_cause.strip()
    if narrative:
        rc_parts.append(narrative)
        rc_sources.append(
            EmbeddingSourceRef(
                field_path="A3Case.root_cause",
                version_token=case_ver,
            ),
        )
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.ROOT_CAUSE,
            text="\n".join(rc_parts),
            sources=rc_sources,
        ),
    )

    scen_text = ""
    scen_sources: list[EmbeddingSourceRef] = []
    if structured is not None:
        ordered = sorted(
            s.strip()
            for s in structured.applicable_scenarios
            if isinstance(s, str) and s.strip()
        )
        scen_text = ", ".join(ordered)
        if scen_text and enrich_ver:
            scen_sources = [
                EmbeddingSourceRef(
                    field_path=(
                        "CaseEnrichmentResult."
                        "structured_suggestions.applicable_scenarios"
                    ),
                    version_token=enrich_ver,
                ),
            ]
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.APPLICABLE_SCENARIOS,
            text=scen_text,
            sources=scen_sources,
        ),
    )

    tags_raw = consumable.tag_suggestions if consumable is not None else []
    tag_ordered = sorted(
        t.strip() for t in tags_raw if isinstance(t, str) and t.strip()
    )
    tags_text = ", ".join(tag_ordered)
    tags_sources: list[EmbeddingSourceRef] = []
    if tags_text and enrich_ver:
        tags_sources = [
            EmbeddingSourceRef(
                field_path="CaseEnrichmentResult.tag_suggestions",
                version_token=enrich_ver,
            ),
        ]
    sections.append(
        EmbeddingInputSection(
            kind=EmbeddingSegmentKind.TAGS,
            text=tags_text,
            sources=tags_sources,
        ),
    )

    return sections


class EmbeddingInputComposer:
    """按固定段落顺序组合问题侧 embedding 输入（不包含解法/效果/方案摘要/推荐）。"""

    def compose_case_input(self, source: IndexSourceSnapshot) -> ComposeCaseInputResult:
        """组合案例索引用 embedding 输入；排除解法/效果/方案摘要/推荐类字段。

        Args:
            source: ``CaseIndexSourceProvider`` 提供的索引快照。

        Returns:
            成功时为 ``EmbeddingInput``；不可索引、内容不足或结构化校验失败时为对应拒绝模型。
        """
        if source.not_indexable_reason is not None:
            return EmbeddingComposeNotIndexable(reason=source.not_indexable_reason)

        case = source.case_detail
        if case is None:
            return EmbeddingComposeInsufficient(
                missing_fields=["IndexSourceSnapshot.case_detail"],
            )

        desc = case.problem_description.strip()
        if not desc:
            return EmbeddingComposeInsufficient(
                missing_fields=["A3Case.problem_description"],
            )

        case_ver = case.updated_at.isoformat()
        consumable = source.enrichment_consumable
        structured: StructuredSuggestions | None = None
        enrich_ver: str | None = None

        if consumable is not None:
            enrich_ver = consumable.output_version
            try:
                structured = StructuredSuggestions.model_validate(
                    consumable.structured_suggestions,
                )
            except ValidationError:
                return EmbeddingComposeInsufficient(
                    missing_fields=[
                        "CaseEnrichmentResult.structured_suggestions",
                    ],
                )

        degraded_out: IndexSourceDegradedReason | None = (
            source.degraded_reason if consumable is None else None
        )

        sections = _assemble_case_embedding_sections(
            case,
            desc,
            case_ver,
            consumable,
            structured,
            enrich_ver,
        )

        pieces = [s.text.strip() for s in sections if s.text.strip()]
        joined = "\n\n".join(pieces)
        if not joined.strip():
            return EmbeddingComposeInsufficient(
                missing_fields=["A3Case.problem_description"],
            )

        return EmbeddingInput(
            text=joined,
            sections=sections,
            degraded_reason=degraded_out,
        )

    def compose_query_input(self, query_text: str) -> EmbeddingInput:
        """组合检索查询向量输入（仅 ``query_text`` 单段）。

        Args:
            query_text: 原始查询字符串（会先 ``strip``）。

        Returns:
            仅含 ``QUERY_TEXT`` 段的 ``EmbeddingInput``。

        Raises:
            ValueError: ``strip`` 后为空。
        """
        stripped = query_text.strip()
        if not stripped:
            raise ValueError("query_text must be non-empty")
        return EmbeddingInput(
            text=stripped,
            sections=[
                EmbeddingInputSection(
                    kind=EmbeddingSegmentKind.QUERY_TEXT,
                    text=stripped,
                    sources=[
                        EmbeddingSourceRef(
                            field_path="VectorSearchRequest.query_text",
                            version_token="query",
                        ),
                    ],
                ),
            ],
            degraded_reason=None,
        )
