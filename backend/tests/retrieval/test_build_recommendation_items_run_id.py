"""_build_recommendation_items 须写入 recommendation_run_id，供反馈表与引用解析。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.retrieval.explainer import ExplanationResult
from app.retrieval.schemas import (
    CandidateSnapshot,
    ExplanationStatus,
    ScoreBreakdownSource,
)
from app.retrieval.score_aggregator import AggregatedCandidate
from app.retrieval.structured_similarity import StructuredSimilarityScore
from app.retrieval.service import RecommendationService


def test_build_recommendation_items_sets_recommendation_run_id() -> None:
    """持久化前每条推荐项应带齐所属 run_id，避免反馈 API 与快照 run 不一致（409）。"""
    svc = RecommendationService.__new__(RecommendationService)
    svc._generate_item_id = lambda: "rec_item_testfixed"  # noqa: PLW0108

    now = datetime.now(timezone.utc)
    snap = CandidateSnapshot(
        case_id="case-1",
        vector_id="vec-1",
        vector_similarity_score=0.9,
        case_updated_at=now,
        missing_fields=[],
    )
    ranked = [
        AggregatedCandidate(
            case_id="case-1",
            final_score=0.9,
            score_breakdown={
                "final_score_source": ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
            },
            normalized_scores={},
            effective_weights={},
            final_score_source=ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
        ),
    ]
    struct = StructuredSimilarityScore(
        case_id="case-1",
        score=None,
        status="skipped",
        factors={},
        metadata={},
    )
    expl = ExplanationResult(items=[], status=ExplanationStatus.UNAVAILABLE)

    items = svc._build_recommendation_items(
        "run-abc-001",
        ranked=ranked,
        snapshots=[snap],
        structured_scores=[struct],
        business_scores=[],
        explanation_result=expl,
    )

    assert len(items) == 1
    assert items[0].recommendation_run_id == "run-abc-001"
    assert items[0].recommendation_item_id == "rec_item_testfixed"
