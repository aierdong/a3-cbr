"""FeedbackRepository 幂等 upsert 测试。"""

import pytest
from sqlalchemy import func, select

from app.feedback.models import RecommendationFeedback
from app.feedback.repository import FeedbackRepository


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates_same_target(db_session) -> None:
    """同一用户同一反馈目标重复写入仅保留一条最新记录。"""
    repo = FeedbackRepository(db_session)
    row1 = await repo.upsert_feedback(
        recommendation_run_id="run-a",
        recommendation_item_id=None,
        case_id=None,
        actor_id="actor-1",
        source_channel="admin_web",
        usefulness="useful",
        comment="first",
    )
    fid = row1.feedback_id
    assert row1.usefulness == "useful"
    assert row1.comment == "first"

    row2 = await repo.upsert_feedback(
        recommendation_run_id="run-a",
        recommendation_item_id=None,
        case_id=None,
        actor_id="actor-1",
        source_channel="api",
        usefulness="not_useful",
        comment="second",
    )
    assert row2.feedback_id == fid
    assert row2.usefulness == "not_useful"
    assert row2.comment == "second"
    assert row2.source_channel == "api"

    await db_session.commit()

    count_stmt = select(func.count()).select_from(RecommendationFeedback)
    res = await db_session.execute(count_stmt)
    assert res.scalar_one() == 1


@pytest.mark.asyncio
async def test_upsert_run_level_and_item_level_distinct_rows(db_session) -> None:
    """同一运行下运行级与推荐项级反馈为两条独立记录。"""
    repo = FeedbackRepository(db_session)
    await repo.upsert_feedback(
        recommendation_run_id="run-b",
        recommendation_item_id=None,
        case_id=None,
        actor_id="actor-1",
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )
    await repo.upsert_feedback(
        recommendation_run_id="run-b",
        recommendation_item_id="item-b",
        case_id="case-b",
        actor_id="actor-1",
        source_channel="admin_web",
        usefulness="unknown",
        comment=None,
    )
    await db_session.commit()
    count_stmt = select(func.count()).select_from(RecommendationFeedback)
    res = await db_session.execute(count_stmt)
    assert res.scalar_one() == 2
