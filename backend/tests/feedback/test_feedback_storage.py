"""任务 1.2：反馈表结构、迁移对齐与运行级/推荐项级持久化。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.feedback.models import RecommendationFeedback


@pytest.mark.asyncio
async def test_recommendation_feedback_run_level_and_item_level(db_session) -> None:
    """可保存运行级（item_id NULL）与推荐项级反馈。"""
    run_id = "run-" + uuid.uuid4().hex[:16]
    item_id = "item-" + uuid.uuid4().hex[:16]
    actor = "actor-" + uuid.uuid4().hex[:8]

    run_row = RecommendationFeedback(
        feedback_id="fb-run-" + uuid.uuid4().hex[:12],
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id=actor,
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )
    item_row = RecommendationFeedback(
        feedback_id="fb-item-" + uuid.uuid4().hex[:12],
        recommendation_run_id=run_id,
        recommendation_item_id=item_id,
        case_id="case-001",
        actor_id=actor,
        source_channel="api",
        usefulness="not_useful",
        comment="ok",
    )
    db_session.add_all([run_row, item_row])
    await db_session.commit()

    res = await db_session.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.recommendation_run_id == run_id
        )
    )
    rows = res.scalars().all()
    assert len(rows) == 2
    by_item = {r.recommendation_item_id: r for r in rows}
    assert by_item[None].usefulness == "useful"
    assert by_item[None].case_id is None
    assert by_item[item_id].case_id == "case-001"
    assert by_item[item_id].usefulness == "not_useful"


@pytest.mark.asyncio
async def test_unique_feedback_target_nulls_not_distinct(db_session) -> None:
    """同一用户对同一运行级目标仅允许一条记录（NULL 视为同一）。"""
    run_id = "run-uniq-" + uuid.uuid4().hex[:12]
    actor = "actor-uniq-" + uuid.uuid4().hex[:8]

    first = RecommendationFeedback(
        feedback_id="fb-a-" + uuid.uuid4().hex[:10],
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id=actor,
        source_channel="admin_web",
        usefulness="unknown",
        comment=None,
    )
    db_session.add(first)
    await db_session.commit()

    dup = RecommendationFeedback(
        feedback_id="fb-b-" + uuid.uuid4().hex[:10],
        recommendation_run_id=run_id,
        recommendation_item_id=None,
        case_id=None,
        actor_id=actor,
        source_channel="admin_web",
        usefulness="useful",
        comment=None,
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_same_actor_distinct_item_ids_allowed(db_session) -> None:
    """同一运行下不同推荐项可各有一条反馈。"""
    run_id = "run-multi-" + uuid.uuid4().hex[:12]
    actor = "actor-m-" + uuid.uuid4().hex[:8]
    i1, i2 = "itm-1-" + uuid.uuid4().hex[:8], "itm-2-" + uuid.uuid4().hex[:8]

    db_session.add_all(
        [
            RecommendationFeedback(
                feedback_id="fb-1-" + uuid.uuid4().hex[:10],
                recommendation_run_id=run_id,
                recommendation_item_id=i1,
                case_id="c1",
                actor_id=actor,
                source_channel="api",
                usefulness="useful",
                comment=None,
            ),
            RecommendationFeedback(
                feedback_id="fb-2-" + uuid.uuid4().hex[:10],
                recommendation_run_id=run_id,
                recommendation_item_id=i2,
                case_id="c2",
                actor_id=actor,
                source_channel="api",
                usefulness="useful",
                comment=None,
            ),
        ]
    )
    await db_session.commit()

    res = await db_session.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.recommendation_run_id == run_id
        )
    )
    assert len(res.scalars().all()) == 2
