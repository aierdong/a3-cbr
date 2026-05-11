"""反馈 HTTP 路由烟测（FastAPI + 覆盖 get_db）。"""

import pytest

from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import RecommendationRunCreate


@pytest.mark.asyncio
async def test_post_submit_and_get_list_smoke(test_client, db_session) -> None:
    """POST 提交与 GET 列表联通。"""
    run_id = "api-run-1"
    rr = RecommendationRepository(db_session)
    await rr.create_run(
        RecommendationRunCreate(
            recommendation_run_id=run_id,
            query_text_hash="qh",
            applied_filters={},
            score_weights={},
            contract_version="mvp-1",
            requested_top_k=5,
            reranker_model_id="rm",
        ),
    )
    await db_session.flush()

    submit = await test_client.post(
        "/api/recommendation-feedback",
        json={
            "recommendation_run_id": run_id,
            "usefulness": "useful",
        },
        headers={"X-Actor-Id": "actor-api"},
    )
    assert submit.status_code == 200
    data = submit.json()
    assert data["recommendation_run_id"] == run_id
    assert data["target_scope"] == "run"

    lst = await test_client.get("/api/recommendation-feedback")
    assert lst.status_code == 200
    body = lst.json()
    assert len(body["items"]) >= 1


@pytest.mark.asyncio
async def test_admin_cleanup_trigger_smoke(test_client, db_session) -> None:
    """手动清理端点校验固定枚举并通过。"""
    resp = await test_client.post(
        "/api/admin/cleanup/feedback",
        json={"reason": "schedule_deleted", "requested_by": "system"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "scanned_count" in data
    assert "deleted_count" in data
    assert "duration_ms" in data
