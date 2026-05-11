"""FastAPI 依赖：反馈服务装配。"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.feedback.reference_resolver import RecommendationReferenceResolver
from app.feedback.repository import FeedbackRepository
from app.feedback.service import FeedbackService
from app.retrieval.repository import RecommendationRepository


async def get_feedback_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FeedbackService:
    """每个请求构造注入同一 AsyncSession 的 FeedbackService。"""
    retrieval_repo = RecommendationRepository(session)
    fb_repo = FeedbackRepository(session)
    resolver = RecommendationReferenceResolver(retrieval_repo)
    return FeedbackService(session, fb_repo, resolver)
