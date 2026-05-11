"""FeedbackRepository / FeedbackService 删除幂等测试。"""

import pytest

from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import (
    FeedbackDeleteReason,
    FeedbackDeleteRequest,
    FeedbackDeleteRequestedBy,
)
from app.feedback.service import FeedbackService
from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import RecommendationRunCreate


@pytest.mark.asyncio
async def test_delete_feedback_by_id_counts_and_idempotent(db_session) -> None:
    """按 feedback_id 删除命中一条；重复删除 deleted_count=0。"""
    run_id = "del-run-1"
    retrieval_repo = RecommendationRepository(db_session)
    fb_repo = FeedbackRepository(db_session)
    await retrieval_repo.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=10,
            reranker_model_id="m",
        ),
    )
    await db_session.flush()

    row = await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id="act-1",
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )

    req = FeedbackDeleteRequest(
        feedback_id=row.feedback_id,
        reason=FeedbackDeleteReason.FEEDBACK_DELETED,
        requested_by=FeedbackDeleteRequestedBy.SYSTEM,
    )
    n1, _ = await fb_repo.delete_feedback(req)
    assert n1 == 1

    n2, _ = await fb_repo.delete_feedback(req)
    assert n2 == 0


@pytest.mark.asyncio
async def test_delete_feedback_via_service(db_session) -> None:
    """服务层删除返回稳定响应结构。"""
    run_id = "del-run-2"
    retrieval_repo = RecommendationRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    fb_repo = FeedbackRepository(db_session)
    svc = FeedbackService(fb_repo, resolver)

    await retrieval_repo.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=10,
            reranker_model_id="m",
        ),
    )
    await db_session.flush()

    row = await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id="act-2",
        source_channel="api",
        usefulness="unknown",
        comment=None,
    )

    resp = await svc.delete_feedback(
        FeedbackDeleteRequest(
            feedback_id=row.feedback_id,
            reason=FeedbackDeleteReason.SCHEDULE_DELETED,
            requested_by=FeedbackDeleteRequestedBy.SYSTEM,
        ),
    )
    assert resp.success is True
    assert resp.deleted_count == 1
