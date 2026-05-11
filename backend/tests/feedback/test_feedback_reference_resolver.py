"""RecommendationReferenceResolver 存在性与一致性测试。"""

from datetime import datetime, timezone

import pytest

from app.feedback.exceptions import FeedbackTargetMismatchError, FeedbackTargetNotFoundError
from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.retrieval.models import (
    AggregationStatus,
    RecommendationItemSnapshot,
    RecommendationRun,
    RerankerStatus,
    RunStatus,
)
from app.retrieval.repository import RecommendationRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _insert_run(session, run_id: str) -> None:
    session.add(
        RecommendationRun(
            recommendation_run_id=run_id,
            query_text_hash="h1",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=10,
            returned_count=1,
            vector_candidate_count=5,
            status=RunStatus.SUCCEEDED.value,
            reranker_model_id="m1",
            reranker_status=RerankerStatus.SKIPPED.value,
            aggregation_status=AggregationStatus.SUCCEEDED.value,
            latency_ms=1,
        ),
    )
    await session.flush()


async def _insert_item(
    session,
    *,
    item_id: str,
    run_id: str,
    case_id: str = "case-a",
) -> None:
    now = _utc_now()
    session.add(
        RecommendationItemSnapshot(
            recommendation_item_id=item_id,
            recommendation_run_id=run_id,
            case_id=case_id,
            vector_id="v1",
            rank=1,
            vector_similarity_score=0.5,
            semantic_similarity_score=0.4,
            structured_similarity_score=0.3,
            business_score=0.2,
            final_score=0.9,
            score_breakdown={},
            explanation_status="generated",
            missing_fields={},
            case_updated_at=now,
        ),
    )
    await session.flush()


@pytest.mark.asyncio
async def test_resolve_run_level_success(db_session) -> None:
    """运行存在且 item_id 为 None 时返回运行级引用。"""
    run_id = "run-1"
    await _insert_run(db_session, run_id)
    repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(repo)

    ref = await resolver.resolve_reference(run_id, None)

    assert ref.recommendation_run_id == run_id
    assert ref.recommendation_item_id is None
    assert ref.case_id is None


@pytest.mark.asyncio
async def test_resolve_item_level_success(db_session) -> None:
    """推荐项属于运行时应返回 case_id。"""
    run_id = "run-2"
    item_id = "item-2"
    await _insert_run(db_session, run_id)
    await _insert_item(db_session, item_id=item_id, run_id=run_id, case_id="case-x")
    repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(repo)

    ref = await resolver.resolve_reference(run_id, item_id)

    assert ref.recommendation_run_id == run_id
    assert ref.recommendation_item_id == item_id
    assert ref.case_id == "case-x"


@pytest.mark.asyncio
async def test_resolve_run_not_found(db_session) -> None:
    """运行不存在时抛出 FeedbackTargetNotFoundError。"""
    repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(repo)

    with pytest.raises(FeedbackTargetNotFoundError):
        await resolver.resolve_reference("missing-run", None)


@pytest.mark.asyncio
async def test_resolve_item_not_found(db_session) -> None:
    """推荐项快照不存在时抛出 FeedbackTargetNotFoundError。"""
    run_id = "run-3"
    await _insert_run(db_session, run_id)
    repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(repo)

    with pytest.raises(FeedbackTargetNotFoundError):
        await resolver.resolve_reference(run_id, "missing-item")


@pytest.mark.asyncio
async def test_resolve_item_run_mismatch(db_session) -> None:
    """推荐项不属于给定运行时抛出 FeedbackTargetMismatchError。"""
    run_a = "run-a"
    run_b = "run-b"
    item_id = "item-m"
    await _insert_run(db_session, run_a)
    await _insert_run(db_session, run_b)
    await _insert_item(db_session, item_id=item_id, run_id=run_a)
    repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(repo)

    with pytest.raises(FeedbackTargetMismatchError):
        await resolver.resolve_reference(run_b, item_id)
