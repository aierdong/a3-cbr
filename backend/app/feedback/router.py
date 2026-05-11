"""推荐反馈 HTTP API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.feedback.cleanup import cleanup_orphaned_feedback_once
from app.feedback.deps import get_feedback_service
from app.feedback.exceptions import (
    FeedbackDisabledError,
    FeedbackTargetMismatchError,
    FeedbackTargetNotFoundError,
)
from app.feedback.http_exc import feedback_exception_to_http
from app.feedback.schemas import (
    CleanupResult,
    CleanupTriggerRequest,
    FeedbackCreateRequest,
    FeedbackDeleteRequest,
    FeedbackDeleteResponse,
    FeedbackListResponse,
    FeedbackQuery,
    FeedbackResponse,
    FeedbackStatsQuery,
    FeedbackStatsResponse,
    RunFeedbackResponse,
)
from app.feedback.service import FeedbackService

router = APIRouter(prefix="/api/recommendation-feedback", tags=["recommendation-feedback"])

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackCreateRequest,
    actor_id: Annotated[str, Header(alias="X-Actor-Id")],
    svc: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackResponse:
    """提交运行级或推荐项级反馈。"""
    try:
        return await svc.submit_feedback(body, actor_id=actor_id)
    except (
        FeedbackTargetNotFoundError,
        FeedbackTargetMismatchError,
        FeedbackDisabledError,
    ) as exc:
        raise feedback_exception_to_http(exc) from exc


@router.post("/delete", response_model=FeedbackDeleteResponse)
async def delete_feedback(
    body: FeedbackDeleteRequest,
    svc: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackDeleteResponse:
    """按过滤条件删除反馈（幂等）。"""
    return await svc.delete_feedback(body)


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    query: Annotated[FeedbackQuery, Depends()],
    svc: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackListResponse:
    """分页过滤查询反馈明细。"""
    return await svc.list_feedback(query)


@router.get("/runs/{run_id}", response_model=RunFeedbackResponse)
async def get_run_feedback(
    run_id: str,
    svc: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> RunFeedbackResponse:
    """查询单次推荐运行下的全部反馈。"""
    return await svc.get_run_feedback(run_id)


@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    query: Annotated[FeedbackStatsQuery, Depends()],
    svc: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackStatsResponse:
    """基础统计：数量、有用率与分布。"""
    return await svc.get_stats(query)


@admin_router.post("/cleanup/feedback", response_model=CleanupResult)
async def trigger_feedback_cleanup(
    body: CleanupTriggerRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CleanupResult:
    """运维手动触发悬空反馈清理（校验固定 reason / requested_by）。"""
    _ = body
    return await cleanup_orphaned_feedback_once(session)
