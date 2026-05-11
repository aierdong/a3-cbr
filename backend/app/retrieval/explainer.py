"""RecommendationExplainer：为已排序候选生成推荐解释或结构化降级。

调用上游 RecommendationCopyService 生成推荐理由、可参考解决点、
注意事项和来源引用。文案失败或信息不足时返回结构化降级解释。

不返回任何排序修改或新增候选，不改变候选顺序。

Boundary: RecommendationExplainer_

Design constraints:
- 调用 RecommendationCopyService 时保持输入候选顺序和 case_id
- 文案失败时生成结构化降级解释：推荐理由状态、可用字段、缺失字段、注意事项占位
- 不返回任何排序修改或新增候选

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.enrichment.schemas import (
    RecommendationCandidate,
    RecommendationCopyRequest,
    RecommendationCopyResponse,
    SourceField,
)
from app.enrichment.validators import OutputValidationException
from app.retrieval.schemas import CandidateSnapshot, ExplanationStatus, NormalizedRetrievalQuery

if TYPE_CHECKING:
    from app.enrichment.recommendation_copy import RecommendationCopyService


logger = logging.getLogger(__name__)


# =============================================================================
# Feature Flag: 全局启用开关
# =============================================================================
# TDD Protocol: RED 阶段 flag=False（实现未完成），GREEN 阶段 flag=True（实现完成）
RETRIEVAL_EXPLAINER_ENABLED = True


def is_explainer_enabled() -> bool:
    """检查 RecommendationExplainer 功能是否启用。"""
    return RETRIEVAL_EXPLAINER_ENABLED


# =============================================================================
# 常量
# =============================================================================

# 缺失解释字段列表
_MISSING_EXPLANATION_FIELDS = [
    "recommendation_reason",
    "reference_points",
    "cautions",
    "source_references",
]


def _convert_source_refs(source_references):
    """转换来源引用为字符串列表。"""
    if not source_references:
        return None
    return [
        sf.value if isinstance(sf, SourceField) else str(sf)
        for sf in source_references
    ]


# =============================================================================
# 解释结果 Data Classes
# =============================================================================


@dataclass
class ExplanationItem:
    """单个候选的解释项。"""

    case_id: str
    recommendation_reason: Optional[str] = None
    reference_points: Optional[list[str]] = None
    cautions: Optional[list[str]] = None
    source_references: Optional[list[str]] = None
    status: ExplanationStatus = ExplanationStatus.UNAVAILABLE
    missing_fields: list[str] = None

    def __post_init__(self) -> None:  # noqa: D105
        if self.missing_fields is None:
            self.missing_fields = []

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "case_id": self.case_id,
            "recommendation_reason": self.recommendation_reason,
            "reference_points": self.reference_points,
            "cautions": self.cautions,
            "source_references": self.source_references,
            "status": self.status.value,
            "missing_fields": self.missing_fields,
        }


@dataclass
class ExplanationResult:
    """推荐解释结果。

    包含每个候选的解释项列表和总体状态。
    """

    items: list[ExplanationItem]
    status: ExplanationStatus
    copy_run_id: Optional[str] = None
    metadata: dict[str, Any] = None

    def __post_init__(self) -> None:  # noqa: D105
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "items": [item.to_dict() for item in self.items],
            "status": self.status.value,
            "copy_run_id": self.copy_run_id,
            "metadata": self.metadata,
        }


# =============================================================================
# RecommendationExplainer
# =============================================================================


class RecommendationExplainer:
    """推荐解释生成器。

    职责：
    1. 调用 RecommendationCopyService 生成推荐文案
    2. 文案失败时生成结构化降级解释
    3. 保持输入候选顺序和 case_id

    不职责：
    - 不决定排序
    - 不新增或过滤候选
    - 不改变输入候选顺序
    """

    def __init__(
        self,
        copy_service: RecommendationCopyService,
    ) -> None:
        """初始化 RecommendationExplainer。

        Args:
            copy_service: 推荐文案服务（由 llm-case-enrichment 提供）。
        """
        self._copy_service = copy_service

    async def explain(
        self,
        query: NormalizedRetrievalQuery,
        ranked: Sequence[CandidateSnapshot],
    ) -> ExplanationResult:
        """为已排序候选生成推荐解释或降级说明。

        调用 RecommendationCopyService 时保持输入候选顺序和 case_id。
        文案失败时生成结构化降级解释：推荐理由状态、可用字段、缺失字段、注意事项占位。
        不返回任何排序修改或新增候选。

        Args:
            query: 标准化检索查询。
            ranked: 已排序候选快照列表（来自 ScoreAggregator 输出）。

        Returns:
            ExplanationResult：包含每个候选的解释项列表和总体状态。
        """
        if not ranked:
            return ExplanationResult(
                items=[],
                status=ExplanationStatus.UNAVAILABLE,
                metadata={"reason": "empty_candidates"},
            )

        # 1. 构建 RecommendationCopyRequest
        copy_request = self._build_copy_request(query, ranked)

        # 2. 调用 RecommendationCopyService
        try:
            copy_response = await self._copy_service.generate_copy(copy_request)
            return self._build_success_result(copy_response, ranked)
        except OutputValidationException as exc:
            logger.warning(
                "推荐文案校验失败，触发降级解释: error_code=%s, message=%s",
                exc.error_code,
                exc.message,
            )
            return self._build_fallback_result(
                ranked=ranked,
                reason=f"文案校验失败: {exc.message}",
            )
        except Exception as exc:
            logger.warning(
                "推荐文案生成失败，触发降级解释: exception=%s",
                str(exc),
            )
            return self._build_fallback_result(
                ranked=ranked,
                reason=f"文案生成失败: {str(exc)}",
            )

    def _build_copy_request(
        self,
        query: NormalizedRetrievalQuery,
        ranked: Sequence[CandidateSnapshot],
    ) -> RecommendationCopyRequest:
        """构建推荐文案请求。"""
        candidates = []
        for snapshot in ranked:
            case_summary = snapshot.problem_summary or snapshot.problem_description
            source_fields = {
                "problem_summary": snapshot.problem_summary,
                "problem_description": snapshot.problem_description,
                "core_solution_steps": snapshot.core_solution_steps,
                "outcome_summary": snapshot.outcome_summary,
                "structured_suggestions": snapshot.structured_suggestions,
            }
            candidates.append(
                RecommendationCandidate(
                    case_id=snapshot.case_id,
                    case_summary=case_summary,
                    source_fields=source_fields,
                )
            )
        return RecommendationCopyRequest(
            query_text=query.normalized_query_text,
            candidates=candidates,
        )

    def _build_success_result(
        self,
        copy_response: RecommendationCopyResponse,
        ranked: Sequence[CandidateSnapshot],
    ) -> ExplanationResult:
        """构建成功结果的解释结果。"""
        copy_items_map = {item.case_id: item for item in copy_response.items}
        explanation_items = []

        for snapshot in ranked:
            copy_item = copy_items_map.get(snapshot.case_id)

            if copy_item is None:
                explanation_items.append(
                    ExplanationItem(
                        case_id=snapshot.case_id,
                        status=ExplanationStatus.FALLBACK,
                        missing_fields=_MISSING_EXPLANATION_FIELDS.copy(),
                    )
                )
                continue

            explanation_items.append(
                ExplanationItem(
                    case_id=snapshot.case_id,
                    recommendation_reason=copy_item.reason,
                    reference_points=copy_item.reference_points or None,
                    cautions=copy_item.cautions or None,
                    source_references=_convert_source_refs(copy_item.source_references),
                    status=ExplanationStatus.GENERATED,
                    missing_fields=[],
                )
            )

        return ExplanationResult(
            items=explanation_items,
            status=ExplanationStatus.GENERATED,
            copy_run_id=copy_response.copy_run_id,
            metadata={
                "model_id": copy_response.model_id,
                "token_usage": copy_response.token_usage,
            },
        )

    def _build_fallback_result(
        self,
        ranked: Sequence[CandidateSnapshot],
        reason: str,
    ) -> ExplanationResult:
        """构建降级结果的解释结果。"""
        explanation_items = []

        for snapshot in ranked:
            available_fields = []
            recommendation_reason = None
            reference_points = None
            cautions = None

            if snapshot.problem_summary or snapshot.problem_description:
                available_fields.append("problem_summary")
                recommendation_reason = snapshot.problem_summary or snapshot.problem_description

            if snapshot.core_solution_steps:
                available_fields.append("core_solution_steps")
                reference_points = [snapshot.core_solution_steps]

            if snapshot.outcome_summary:
                available_fields.append("outcome_summary")
                cautions = [f"参考效果: {snapshot.outcome_summary}"]

            if snapshot.structured_suggestions:
                available_fields.append("structured_suggestions")

            actual_missing = [
                f for f in _MISSING_EXPLANATION_FIELDS
                if f not in available_fields
            ]

            explanation_items.append(
                ExplanationItem(
                    case_id=snapshot.case_id,
                    recommendation_reason=recommendation_reason,
                    reference_points=reference_points,
                    cautions=cautions,
                    source_references=None,
                    status=ExplanationStatus.FALLBACK,
                    missing_fields=actual_missing,
                )
            )

        return ExplanationResult(
            items=explanation_items,
            status=ExplanationStatus.FALLBACK,
            metadata={
                "reason": reason,
                "fallback_fields_used": available_fields,
            },
        )
