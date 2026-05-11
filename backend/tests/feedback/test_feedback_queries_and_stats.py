"""反馈明细查询与基础统计集成测试。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import (
    FeedbackQuery,
    FeedbackStatsGroupBy,
    FeedbackStatsQuery,
)
from app.feedback.service import FeedbackService
from app.retrieval.models import RecommendationItemSnapshot, RecommendationRun
from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import RecommendationRunCreate


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_list_feedback_includes_query_context_and_item_detail(db_session) -> None:
    """明细查询应带出运行上下文字段与推荐项分值摘要。"""
    run_id = "q-run-1"
    item_id = "q-item-1"
    retrieval_repo = RecommendationRepository(db_session)
    await retrieval_repo.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh1",
            applied_filters={"k": "v"},
            score_weights={"vector": 0.3},
            contract_version="mvp-1",
            requested_top_k=5,
            reranker_model_id="rm",
        ),
    )
    await db_session.execute(
        update(RecommendationRun)
        .where(RecommendationRun.recommendation_run_id == run_id)
        .values(returned_count=2, vector_candidate_count=10),
    )
    now = _utc_now()
    db_session.add(
        RecommendationItemSnapshot(
            recommendation_item_id=item_id,
            recommendation_run_id=run_id,
            case_id="case-q",
            vector_id="vid",
            rank=1,
            vector_similarity_score=0.7,
            semantic_similarity_score=0.6,
            structured_similarity_score=0.5,
            business_score=0.4,
            final_score=0.91,
            score_breakdown={},
            explanation_status="generated",
            missing_fields={},
            case_updated_at=now,
        ),
    )
    await db_session.flush()

    fb_repo = FeedbackRepository(db_session)
    await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=item_id,
        case_id="case-q",
        actor_id="actor-q",
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )

    svc = FeedbackService(
        db_session,
        fb_repo,
        RecommendationReferenceResolver(retrieval_repo),
    )
    resp = await svc.list_feedback(FeedbackQuery(limit=10, offset=0))
    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.query_context is not None
    assert item.query_context.query_hash == "qh1"
    assert item.query_context.returned_count == 2
    assert item.query_context.vector_candidate_count == 10
    assert '"k"' in item.query_context.applied_filters_summary
    assert item.item_detail is not None
    assert item.item_detail.final_score == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_get_run_feedback_lists_run_and_item_targets(db_session) -> None:
    """单次运行查询同时包含运行级与推荐项级记录。"""
    run_id = "q-run-2"
    item_id = "q-item-2"
    retrieval_repo = RecommendationRepository(db_session)
    await retrieval_repo.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh2",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=3,
            reranker_model_id="rm",
        ),
    )
    now = _utc_now()
    db_session.add(
        RecommendationItemSnapshot(
            recommendation_item_id=item_id,
            recommendation_run_id=run_id,
            case_id="case-z",
            vector_id="vid",
            rank=1,
            vector_similarity_score=0.5,
            semantic_similarity_score=None,
            structured_similarity_score=None,
            business_score=None,
            final_score=0.8,
            score_breakdown={},
            explanation_status="fallback",
            missing_fields={},
            case_updated_at=now,
        ),
    )
    await db_session.flush()

    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id="a1",
        source_channel="admin_web",
        usefulness="unknown",
        comment=None,
    )
    await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=item_id,
        case_id="case-z",
        actor_id="a1",
        source_channel="api",
        usefulness="useful",
        comment=None,
    )

    svc = FeedbackService(db_session, fb_repo, resolver)
    run_fb = await svc.get_run_feedback(run_id)
    assert run_fb.recommendation_run_id == run_id
    assert len(run_fb.items) == 2


@pytest.mark.asyncio
async def test_stats_empty_table_zero_overall(db_session) -> None:
    """无记录时统计为零值而非报错。"""
    fb_repo = FeedbackRepository(db_session)
    svc = FeedbackService(
        db_session,
        fb_repo,
        RecommendationReferenceResolver(RecommendationRepository(db_session)),
    )
    stats = await svc.get_stats(FeedbackStatsQuery())
    assert stats.overall.total_count == 0
    assert stats.overall.useful_rate == 0.0


@pytest.mark.asyncio
async def test_stats_counts_usefulness(db_session) -> None:
    """有用性分布与计数正确。"""
    run_id = "st-run"
    retrieval_repo = RecommendationRepository(db_session)
    await retrieval_repo.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=3,
            reranker_model_id="rm",
        ),
    )
    await db_session.flush()
    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id="u1",
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )
    await fb_repo.upsert_feedback(
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id="u2",
        source_channel="admin_web",
        usefulness="not_useful",
        comment=None,
    )

    svc = FeedbackService(db_session, fb_repo, resolver)
    stats = await svc.get_stats(FeedbackStatsQuery())
    assert stats.overall.total_count == 2
    assert stats.overall.useful_count == 1
    assert stats.overall.not_useful_count == 1
    assert stats.overall.useful_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_stats_group_by_run(db_session) -> None:
    """按推荐运行分组聚合。"""
    retrieval_repo = RecommendationRepository(db_session)
    for rid in ("g1", "g2"):
        await retrieval_repo.create_run(
            RecommendationRunCreate(
                recommendation_run_id=rid,
                query_text_hash="qh",
                applied_filters={},
                score_weights={},
                contract_version="mvp-1",
                requested_top_k=3,
                reranker_model_id="rm",
            ),
        )
    await db_session.flush()
    fb_repo = FeedbackRepository(db_session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    await fb_repo.upsert_feedback(
        recommendation_run_id="g1",
        recommendation_item_id=None,
        case_id=None,
        actor_id="x1",
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )
    await fb_repo.upsert_feedback(
        recommendation_run_id="g2",
        recommendation_item_id=None,
        case_id=None,
        actor_id="x2",
        source_channel="admin_web",
        usefulness="unknown",
        comment=None,
    )

    svc = FeedbackService(db_session, fb_repo, resolver)
    stats = await svc.get_stats(
        FeedbackStatsQuery(group_by=FeedbackStatsGroupBy.RECOMMENDATION_RUN),
    )
    assert len(stats.groups) == 2
