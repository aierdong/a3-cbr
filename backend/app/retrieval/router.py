"""相似案例推荐 API 路由。

暴露手动相似案例推荐入口和推荐运行查询端点。

Responsibilities:
- 接收请求并调用 RecommendationService，不直接访问数据库
- 使用 RetrievalSchemas 固定请求和响应结构
- 将领域错误映射为一致 HTTP 错误响应

Requirements: 1.1, 1.3, 4.1, 5.1, 7.2
Boundary: RetrievalRouter
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_app_config
from app.core.errors import (
    ErrorCode,
    ErrorResponse,
    create_error_response,
)
from app.db.session import get_db
from app.retrieval.query import QueryNormalizer
from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import (
    RecommendationResponse,
    RecommendationRunResponse,
    RetrievalRequest,
)
from app.retrieval.service import RecommendationService
from app.retrieval.vector_port import VectorSearchPort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def get_recommendation_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendationService:
    """构造 ``RecommendationService`` 实例。

    Args:
        session: 数据库会话。

    Returns:
        推荐服务实例。
    """
    config = get_app_config()
    repository = RecommendationRepository(session)

    normalizer_llm_config = config.normalizer_llm
    retrieval_config = config.retrieval

    normalizer = QueryNormalizer(
        config=normalizer_llm_config,
        top_k_upper_bound=retrieval_config.top_k_upper_bound,
        business_weights_upper_bound=retrieval_config.business_weights_upper_bound,
    )

    vector_port = VectorSearchPort(retrieval_config=retrieval_config)

    return RecommendationService(
        repository=repository,
        normalizer=normalizer,
        vector_port=vector_port,
        config=retrieval_config,
    )


@router.post(
    "/similar-cases",
    response_model=RecommendationResponse,
    responses={
        422: {"model": ErrorResponse, "description": "校验失败"},
        503: {"model": ErrorResponse, "description": "服务不可用"},
    },
    summary="相似案例推荐",
    description="输入当前问题文本、Top-K、过滤条件和可选业务权重，返回相似案例推荐列表。",
)
async def recommend_similar_cases(
    request: RetrievalRequest,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationResponse:
    """执行相似案例推荐。

    流程：
    1. 校验请求（query_text 非空、top_k 在范围内）
    2. 创建运行记录（create_run）
    3. 查询标准化（LLM normalizer）
    4. 向量搜索候选消费
    5. 候选快照读取
    6. 结构化局部评分（MVP skipped）
    7. 业务参数评分
    8. 语义精排（reranker）
    9. 分值聚合
    10. 推荐解释
    11. 结果组装

    Args:
        request: 检索请求。
        service: 推荐服务实例。

    Returns:
        推荐响应。
    """
    try:
        return await service.recommend_similar_cases(request)
    except Exception as exc:
        logger.error("相似案例推荐失败: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="推荐服务暂时不可用，请稍后重试",
            ).model_dump(),
        )


@router.get(
    "/runs/{run_id}",
    response_model=RecommendationRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "运行不存在"},
    },
    summary="查询推荐运行记录",
    description="通过运行标识查询推荐运行状态和候选快照元数据。",
)
async def get_recommendation_run(
    run_id: str,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationRunResponse:
    """查询推荐运行记录。

    Args:
        run_id: 运行标识。
        service: 推荐服务实例。

    Returns:
        推荐运行响应。

    Raises:
        HTTPException: 运行不存在时返回 404。
    """
    result = await service.get_run(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=ErrorCode.CASE_NOT_FOUND,
                message=f"recommendation run not found: {run_id}",
            ).model_dump(),
        )
    return result
