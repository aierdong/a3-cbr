"""任务 1.3：反馈 Pydantic 契约校验测试。"""

import pytest
from datetime import datetime, timezone

from app.core.config import get_app_config
from app.feedback.schemas import (
    CleanupTriggerRequest,
    FeedbackCreateRequest,
    FeedbackDeleteReason,
    FeedbackDeleteRequest,
    FeedbackDeleteRequestedBy,
    FeedbackListItem,
    FeedbackResponse,
    FeedbackSourceChannel,
    FeedbackStatsGroupRow,
    FeedbackStatsResponse,
    FeedbackTargetScope,
    FeedbackUsefulness,
    ItemRecommendationDetail,
    NormalizedFeedbackInput,
    QueryContextSummary,
)


def test_feedback_create_request_defaults_and_usefulness() -> None:
    """提交请求默认来源渠道与可选 item_id。"""
    req = FeedbackCreateRequest(
        recommendation_run_id="run-1",
        usefulness=FeedbackUsefulness.USEFUL,
    )
    assert req.source_channel == FeedbackSourceChannel.ADMIN_WEB
    assert req.recommendation_item_id is None
    assert req.comment is None


def test_feedback_create_run_id_trimmed() -> None:
    """run_id 首尾空白应去除。"""
    req = FeedbackCreateRequest(
        recommendation_run_id="  run-x  ",
        usefulness=FeedbackUsefulness.UNKNOWN,
    )
    assert req.recommendation_run_id == "run-x"


def test_feedback_create_run_id_rejects_blank() -> None:
    """run_id 不得为空或纯空白。"""
    with pytest.raises(ValueError):
        FeedbackCreateRequest(
            recommendation_run_id="   ",
            usefulness=FeedbackUsefulness.UNKNOWN,
        )


def test_feedback_create_item_id_rejects_blank_when_provided() -> None:
    """提供推荐项 id 时不得为纯空白字符串。"""
    with pytest.raises(ValueError):
        FeedbackCreateRequest(
            recommendation_run_id="run-1",
            recommendation_item_id=" \t ",
            usefulness=FeedbackUsefulness.NOT_USEFUL,
        )


def test_feedback_create_comment_whitespace_becomes_none() -> None:
    """备注仅为空白时视为未提供。"""
    req = FeedbackCreateRequest(
        recommendation_run_id="run-1",
        usefulness=FeedbackUsefulness.USEFUL,
        comment="   \n",
    )
    assert req.comment is None


def test_normalized_feedback_input_run_vs_item() -> None:
    """规范化输入应明确区分运行级与推荐项级目标。"""
    run_req = FeedbackCreateRequest(
        recommendation_run_id="run-1",
        usefulness=FeedbackUsefulness.USEFUL,
    )
    norm_run = run_req.to_normalized_input()
    assert isinstance(norm_run, NormalizedFeedbackInput)
    assert norm_run.target_scope == FeedbackTargetScope.RUN
    assert norm_run.recommendation_item_id is None

    item_req = FeedbackCreateRequest(
        recommendation_run_id="run-1",
        recommendation_item_id="item-9",
        usefulness=FeedbackUsefulness.NOT_USEFUL,
        source_channel=FeedbackSourceChannel.API,
    )
    norm_item = NormalizedFeedbackInput.from_create_request(item_req)
    assert norm_item.target_scope == FeedbackTargetScope.ITEM
    assert norm_item.recommendation_item_id == "item-9"
    assert norm_item.source_channel == FeedbackSourceChannel.API


def test_feedback_create_comment_respects_max_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """备注长度受 FEEDBACK_COMMENT_MAX_LENGTH 约束。"""
    monkeypatch.setenv("FEEDBACK_COMMENT_MAX_LENGTH", "5")
    get_app_config.cache_clear()
    try:
        with pytest.raises(ValueError, match="comment exceeds max length"):
            FeedbackCreateRequest(
                recommendation_run_id="run-1",
                usefulness=FeedbackUsefulness.UNKNOWN,
                comment="123456",
            )
    finally:
        monkeypatch.delenv("FEEDBACK_COMMENT_MAX_LENGTH", raising=False)
        get_app_config.cache_clear()


def test_feedback_delete_requires_at_least_one_filter() -> None:
    """删除请求必须包含至少一个目标过滤字段。"""
    with pytest.raises(ValueError, match="at least one of"):
        FeedbackDeleteRequest(
            reason=FeedbackDeleteReason.CASE_DELETED,
            requested_by=FeedbackDeleteRequestedBy.SYSTEM,
        )


def test_feedback_delete_with_feedback_id_ok() -> None:
    """提供 feedback_id 时删除请求应通过模型校验。"""
    req = FeedbackDeleteRequest(
        feedback_id="fb-1",
        reason=FeedbackDeleteReason.FEEDBACK_DELETED,
        requested_by=FeedbackDeleteRequestedBy.ANONYMOUS_USER,
    )
    assert req.feedback_id == "fb-1"


def test_cleanup_trigger_fixed_enumerations() -> None:
    """手动清理触发仅允许 schedule_deleted + system。"""
    CleanupTriggerRequest(
        reason=FeedbackDeleteReason.SCHEDULE_DELETED,
        requested_by=FeedbackDeleteRequestedBy.SYSTEM,
    )
    with pytest.raises(ValueError, match="reason must be schedule_deleted"):
        CleanupTriggerRequest(
            reason=FeedbackDeleteReason.CASE_DELETED,
            requested_by=FeedbackDeleteRequestedBy.SYSTEM,
        )
    with pytest.raises(ValueError, match="requested_by must be system"):
        CleanupTriggerRequest(
            reason=FeedbackDeleteReason.SCHEDULE_DELETED,
            requested_by=FeedbackDeleteRequestedBy.ANONYMOUS_USER,
        )


def test_feedback_list_item_optional_join_fields() -> None:
    """列表项可携带关联查询上下文与可选 item 明细。"""
    now = datetime.now(timezone.utc)
    base = FeedbackResponse(
        feedback_id="f1",
        recommendation_run_id="run-1",
        recommendation_item_id=None,
        case_id=None,
        usefulness=FeedbackUsefulness.NOT_USEFUL,
        comment=None,
        target_scope=FeedbackTargetScope.RUN,
        created_at=now,
        updated_at=now,
    )
    item = FeedbackListItem(
        **base.model_dump(),
        actor_id="u1",
        source_channel=FeedbackSourceChannel.API,
        query_context=QueryContextSummary(
            query_hash="h" * 64,
            applied_filters_summary="{}",
            vector_candidate_count=10,
            returned_count=3,
        ),
        item_detail=None,
    )
    assert item.query_context is not None
    assert item.query_context.returned_count == 3


def test_feedback_stats_response_zero_overall() -> None:
    """统计响应允许全零总体口径。"""
    overall = FeedbackStatsGroupRow(
        dimension="none",
        total_count=0,
        useful_count=0,
        not_useful_count=0,
        unknown_count=0,
        useful_rate=0.0,
        not_useful_rate=0.0,
        unknown_rate=0.0,
    )
    body = FeedbackStatsResponse(overall=overall, groups=[])
    assert body.overall.total_count == 0


def test_item_recommendation_detail_schema() -> None:
    """推荐项关联明细 schema 可实例化。"""
    d = ItemRecommendationDetail(
        rank=1,
        vector_similarity_score=0.9,
        semantic_similarity_score=None,
        structured_similarity_score=None,
        business_score=None,
        final_score=0.88,
        explanation_status="generated",
    )
    assert d.rank == 1
