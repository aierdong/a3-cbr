"""相关性过滤单元测试。

验证基于 reranker 原始语义分（或向量降级）的低相关候选剔除逻辑。

Boundary: RelevanceFilter_
"""

from __future__ import annotations

from app.retrieval.relevance_filter import (
    SEMANTIC_ABSOLUTE_FLOOR,
    SEMANTIC_RELATIVE_RATIO,
    VECTOR_FALLBACK_FLOOR,
    classify_semantic_confidence,
    filter_relevant_candidates,
)
from app.retrieval.score_aggregator import AggregatedCandidate
from app.retrieval.schemas import ScoreBreakdownSource


def _make_candidate(
    case_id: str,
    *,
    semantic: float | None = None,
    vector: float = 0.78,
    final_score: float = 0.5,
) -> AggregatedCandidate:
    return AggregatedCandidate(
        case_id=case_id,
        final_score=final_score,
        score_breakdown={
            "vector_similarity_score": vector,
            "semantic_similarity_score": semantic,
            "final_score_source": ScoreBreakdownSource.AGGREGATED,
        },
        normalized_scores={},
        effective_weights={},
        final_score_source=ScoreBreakdownSource.AGGREGATED,
    )


def _batch_20_with_single_relevant_top() -> list[AggregatedCandidate]:
    """复现 batch 失真场景：#1 语义 0.75，其余约 1e-6~6e-5。"""
    items = [_make_candidate("case-1", semantic=0.75, vector=0.79, final_score=0.72)]
    tail_scores = [1e-6, 2e-6, 3e-6, 4e-6, 5e-6, 6e-5, 5e-5, 4e-5, 3e-5, 2e-5]
    tail_scores += [1e-5, 2e-5, 3e-5, 4e-5, 5e-5, 6e-6, 7e-6, 8e-6, 9e-6]
    for idx, sem in enumerate(tail_scores, start=2):
        items.append(
            _make_candidate(
                f"case-{idx}",
                semantic=sem,
                vector=0.67 + idx * 0.005,
                final_score=0.25 + idx * 0.01,
            )
        )
    assert len(items) == 20
    return items


class TestFilterRelevantCandidates:
    """filter_relevant_candidates 核心路径。"""

    def test_semantic_batch_keeps_only_top_relevant(self) -> None:
        """20 条候选在语义门槛下应只保留 #1。"""
        items = _batch_20_with_single_relevant_top()
        result = filter_relevant_candidates(items, reranker_ok=True)

        assert result.filter_mode == "semantic"
        assert result.applied_floor == max(
            SEMANTIC_ABSOLUTE_FLOOR,
            0.75 * SEMANTIC_RELATIVE_RATIO,
        )
        assert result.input_count == 20
        assert result.output_count == 1
        assert [c.case_id for c in result.candidates] == ["case-1"]

    def test_vector_fallback_when_reranker_failed(self) -> None:
        """reranker 失败时退回向量分门槛。"""
        items = [
            _make_candidate("high-vector", semantic=None, vector=0.90),
            _make_candidate("low-vector", semantic=None, vector=0.70),
            _make_candidate("border", semantic=None, vector=VECTOR_FALLBACK_FLOOR),
        ]
        result = filter_relevant_candidates(items, reranker_ok=False)

        assert result.filter_mode == "vector_fallback"
        assert result.applied_floor == VECTOR_FALLBACK_FLOOR
        assert [c.case_id for c in result.candidates] == ["high-vector", "border"]

    def test_all_filtered_returns_empty(self) -> None:
        """全部低于门槛时返回空列表。"""
        items = [
            _make_candidate("a", semantic=0.05, vector=0.60),
            _make_candidate("b", semantic=0.08, vector=0.65),
        ]
        result = filter_relevant_candidates(items, reranker_ok=True)

        assert result.candidates == []
        assert result.output_count == 0
        assert result.applied_floor == SEMANTIC_ABSOLUTE_FLOOR

    def test_empty_input(self) -> None:
        """空输入返回空结果。"""
        result = filter_relevant_candidates([], reranker_ok=True)
        assert result.candidates == []
        assert result.applied_floor is None

    def test_preserves_final_score_order(self) -> None:
        """幸存者保持原排序顺序。"""
        items = [
            _make_candidate("b", semantic=0.80, final_score=0.9),
            _make_candidate("a", semantic=0.50, final_score=0.8),
            _make_candidate("c", semantic=0.20, final_score=0.7),
        ]
        result = filter_relevant_candidates(items, reranker_ok=True)
        assert [c.case_id for c in result.candidates] == ["b", "a"]

    def test_top_k_applied_after_filter(self) -> None:
        """过滤后再截取 Top-K。"""
        items = [
            _make_candidate("a", semantic=0.80),
            _make_candidate("b", semantic=0.60),
            _make_candidate("c", semantic=0.40),
        ]
        result = filter_relevant_candidates(items, reranker_ok=True, top_k=2)
        assert len(result.candidates) == 2
        assert [c.case_id for c in result.candidates] == ["a", "b"]


class TestClassifySemanticConfidence:
    """可信度分层辅助函数。"""

    def test_tiers(self) -> None:
        assert classify_semantic_confidence(0.05) == "irrelevant"
        assert classify_semantic_confidence(0.15) == "low_confidence"
        assert classify_semantic_confidence(0.30) == "confident"
        assert classify_semantic_confidence(0.55) == "high_confidence"
