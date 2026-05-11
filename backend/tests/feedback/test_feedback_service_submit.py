"""FeedbackService 提交路径集成测试。"""

from datetime import datetime, timezone

import pytest

from app.core.config import get_app_config
from app.feedback.exceptions import FeedbackDisabledError, FeedbackTargetNotFoundError
from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import FeedbackCreateRequest, FeedbackSourceChannel, FeedbackTargetScope
from app.feedback.service import FeedbackService
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


async def _seed_run(db_session, run_id: str) -> None:
    db_session.add(
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
    await db_session.flush()


async def _seed_item(db_session, *, item_id: str, run_id: str, case_id: str) -> None:
    now = _utc_now()
    db_session.add(
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
    await db_session.flush()


@pytest.mark.asyncio
async def test_submit_feedback_run_level(db_session) -> None:
    """运行级反馈写入且响应标记为 RUN。"""
    run_id = "svc-run-1"
    await _seed_run(db_session, run_id)
    retrieval_repo = RecommendationRepository(db_session)
    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    service = FeedbackService(fb_repo, resolver)

    req = FeedbackCreateRequest(
        recommendation_run_id=run_id,
        usefulness="useful",
        source_channel=FeedbackSourceChannel.API,
    )
    resp = await service.submit_feedback(req, actor_id="actor-x")

    assert resp.target_scope == FeedbackTargetScope.RUN
    assert resp.recommendation_item_id is None
    assert resp.case_id is None


@pytest.mark.asyncio
async def test_submit_feedback_item_level(db_session) -> None:
    """推荐项级反馈写入 case_id。"""
    run_id = "svc-run-2"
    item_id = "svc-item-2"
    await _seed_run(db_session, run_id)
    await _seed_item(db_session, item_id=item_id, run_id=run_id, case_id="case-z")
    retrieval_repo = RecommendationRepository(db_session)
    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    service = FeedbackService(fb_repo, resolver)

    req = FeedbackCreateRequest(
        recommendation_run_id=run_id,
        recommendation_item_id=item_id,
        usefulness="not_useful",
    )
    resp = await service.submit_feedback(req, actor_id="actor-y")

    assert resp.target_scope == FeedbackTargetScope.ITEM
    assert resp.case_id == "case-z"


@pytest.mark.asyncio
async def test_submit_feedback_propagates_target_not_found(db_session) -> None:
    """上游运行不存在时抛出 FeedbackTargetNotFoundError。"""
    retrieval_repo = RecommendationRepository(db_session)
    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    service = FeedbackService(fb_repo, resolver)

    req = FeedbackCreateRequest(
        recommendation_run_id="no-run",
        usefulness="unknown",
    )
    with pytest.raises(FeedbackTargetNotFoundError):
        await service.submit_feedback(req, actor_id="actor-z")


@pytest.mark.asyncio
async def test_submit_feedback_disabled(monkeypatch: pytest.MonkeyPatch, db_session) -> None:
    """FEEDBACK_ENABLED=false 时拒绝提交。"""
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    get_app_config.cache_clear()
    try:
        run_id = "svc-run-off"
        await _seed_run(db_session, run_id)
        retrieval_repo = RecommendationRepository(db_session)
        fb_repo = FeedbackRepository(db_session)
        resolver = RecommendationReferenceResolver(retrieval_repo)
        service = FeedbackService(fb_repo, resolver)

        req = FeedbackCreateRequest(
            recommendation_run_id=run_id,
            usefulness="useful",
        )
        with pytest.raises(FeedbackDisabledError):
            await service.submit_feedback(req, actor_id="actor-off")
    finally:
        monkeypatch.delenv("FEEDBACK_ENABLED", raising=False)
        get_app_config.cache_clear()
