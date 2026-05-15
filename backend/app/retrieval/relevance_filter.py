"""相关性过滤：基于 reranker 原始语义分剔除无关候选。

ScoreAggregator 在 batch 内 min-max 归一化后加权求和，``final_score`` 会失真，
不能作为主过滤信号。本模块在聚合排序之后、返回 Top-K 之前，依据 reranker
原始 ``semantic_similarity_score``（或 reranker 失败时的向量分降级）过滤低相关候选。

Boundary: RelevanceFilter_
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from app.retrieval.score_aggregator import AggregatedCandidate


# =============================================================================
# 默认阈值
# =============================================================================

SEMANTIC_ABSOLUTE_FLOOR = 0.10
SEMANTIC_RELATIVE_RATIO = 0.35
SEMANTIC_LOW_CONFIDENCE = 0.25
VECTOR_FALLBACK_FLOOR = 0.75


# =============================================================================
# 配置与结果
# =============================================================================


@dataclass(frozen=True)
class RelevanceFilterConfig:
    """相关性过滤阈值配置。"""

    semantic_absolute_floor: float = SEMANTIC_ABSOLUTE_FLOOR
    semantic_relative_ratio: float = SEMANTIC_RELATIVE_RATIO
    semantic_low_confidence: float = SEMANTIC_LOW_CONFIDENCE
    vector_fallback_floor: float = VECTOR_FALLBACK_FLOOR


@dataclass(frozen=True)
class RelevanceFilterResult:
    """相关性过滤结果。"""

    candidates: list[AggregatedCandidate]
    applied_floor: Optional[float]
    filter_mode: str
    input_count: int
    output_count: int


# =============================================================================
# 可信度分层（供 UI / 元数据使用）
# =============================================================================


def classify_semantic_confidence(
    score: float,
    *,
    config: RelevanceFilterConfig | None = None,
) -> str:
    """按原始语义分划分可信度层级。

    Args:
        score: reranker 原始语义相似度（0~1）。
        config: 阈值配置；默认使用模块常量。

    Returns:
        可信度标签：``irrelevant`` | ``low_confidence`` | ``confident`` | ``high_confidence``。
    """
    cfg = config or RelevanceFilterConfig()
    if score < cfg.semantic_absolute_floor:
        return "irrelevant"
    if score < cfg.semantic_low_confidence:
        return "low_confidence"
    if score >= 0.50:
        return "high_confidence"
    return "confident"


def _score_from_breakdown(
    candidate: AggregatedCandidate,
    key: str,
) -> float:
    value = candidate.score_breakdown.get(key)
    if value is None:
        return 0.0
    return float(value)


def _compute_semantic_floor(
    scores: Sequence[float],
    config: RelevanceFilterConfig,
) -> float:
    top_sem = max(scores)
    return max(
        config.semantic_absolute_floor,
        top_sem * config.semantic_relative_ratio,
    )


def filter_relevant_candidates(
    sorted_items: Sequence[AggregatedCandidate],
    *,
    reranker_ok: bool,
    top_k: int | None = None,
    config: RelevanceFilterConfig | None = None,
) -> RelevanceFilterResult:
    """过滤低相关候选，保留原 ``final_score`` 排序顺序。

    Args:
        sorted_items: 聚合排序后的候选列表。
        reranker_ok: reranker 成功时为 True，走语义门槛；否则退回向量分过滤。
        top_k: 过滤后截取的上限；为 None 时不截取。
        config: 阈值配置；默认使用模块常量。

    Returns:
        过滤结果，含幸存候选与元数据。
    """
    cfg = config or RelevanceFilterConfig()
    input_count = len(sorted_items)

    if not sorted_items:
        return RelevanceFilterResult(
            candidates=[],
            applied_floor=None,
            filter_mode="semantic" if reranker_ok else "vector_fallback",
            input_count=0,
            output_count=0,
        )

    if reranker_ok:
        scores = [
            _score_from_breakdown(item, "semantic_similarity_score")
            for item in sorted_items
        ]
        sem_floor = _compute_semantic_floor(scores, cfg)
        kept = [
            item
            for item, score in zip(sorted_items, scores, strict=True)
            if score >= sem_floor
        ]
        filter_mode = "semantic"
        applied_floor = sem_floor
    else:
        kept = [
            item
            for item in sorted_items
            if _score_from_breakdown(item, "vector_similarity_score")
            >= cfg.vector_fallback_floor
        ]
        filter_mode = "vector_fallback"
        applied_floor = cfg.vector_fallback_floor

    if top_k is not None and top_k > 0:
        kept = kept[:top_k]

    return RelevanceFilterResult(
        candidates=kept,
        applied_floor=applied_floor,
        filter_mode=filter_mode,
        input_count=input_count,
        output_count=len(kept),
    )
