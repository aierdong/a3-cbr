"""RetrievalRouter：相似案例推荐 API 路由。

提供手动相似案例推荐 HTTP 入口：
- POST `/api/recommendations/similar-cases`：手动相似案例推荐入口
- GET `/api/recommendations/runs/{run_id}`：返回推荐运行状态和候选快照元数据

Requirements: 1.1, 1.3, 1.4, 1.5, 5.1, 7.2
Boundary: RetrievalRouter_
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.llm_client import LLMClient
from app.core.config import (
    AppConfig,
    NormalizerLLMConfig,
    RerankerConfig,
    get_app_config,
)
from app.core.errors import (
    ErrorCode,
    ErrorResponse,
    create_error_response,
)
from app.db.session import get_db
from app.enrichment.repository import EnrichmentRepository
from app.retrieval.business_scoring import BusinessScoreCalculator
from app.retrieval.case_provider import RecommendationCaseProvider
from app.retrieval.query import QueryNormalizer
from app.retrieval.reranker_client import RerankerClient
from app.retrieval.repository import RecommendationRepository
from app.retrieval.schemas import (
    RecommendationResponse,
    RecommendationRunResponse,
    RetrievalRequest,
    ValidationErrorDetail,
    ValidationErrorResponse,
)
from app.retrieval.service import RecommendationService
from app.retrieval.structured_similarity import StructuredSimilarityScorer
from app.retrieval.vector_port import VectorSearchPort


logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


# =============================================================================
# 依赖注入工厂
# =============================================================================


def _build_retrieval_service(
    session: AsyncSession,
    config: AppConfig,
) -> RecommendationService:
    """构建 RecommendationService 实例及其全部依赖。

    Args:
        session: 数据库会话。
        config: 应用配置。

    Returns:
        配置完整的推荐服务实例。
    """
    # 1. 仓储层
    repository = RecommendationRepository(session)

    # 2. LLM Client（共享）
    llm_client = LLMClient()

    # 3. NormalizerLLMConfig
    normalizer_config = NormalizerLLMConfig(
        api_key=config.normalizer_llm.api_key,
        model_id=config.normalizer_llm.model_id,
        base_url=config.normalizer_llm.base_url,
        timeout_ms=config.normalizer_llm.timeout_ms,
        max_retries=config.normalizer_llm.max_retries,
    )

    # 4. QueryNormalizer
    normalizer = QueryNormalizer(
        llm_client=llm_client,
        config=normalizer_config,
    )

    # 5. VectorSearchPort
    vector_port = VectorSearchPort()

    # 6. CaseProvider 依赖
    from app.cases.repository import CaseRepository
    from app.cases.service import CaseService
    from app.cases.validators import CaseValidator

    case_repository = CaseRepository(session)
    case_validator = CaseValidator()
    case_service = CaseService(case_repository, case_validator)
    enrichment_repository = EnrichmentRepository(session)

    case_provider = RecommendationCaseProvider(
        case_service=case_service,
        enrichment_repository=enrichment_repository,
    )

    # 7. StructuredSimilarityScorer
    structured_scorer = StructuredSimilarityScorer()

    # 8. BusinessScoreCalculator
    business_scorer = BusinessScoreCalculator()

    # 9. RerankerConfig
    reranker_config = RerankerConfig(
        api_key=config.reranker.api_key,
        model_id=config.reranker.model_id,
        base_url=config.reranker.base_url,
        timeout_ms=config.reranker.timeout_ms,
        max_retries=config.reranker.max_retries,
    )

    # 10. RerankerClient
    reranker = RerankerClient(config=reranker_config)

    # 11. ScoreAggregator（导入滞后避免循环）
    from app.retrieval.score_aggregator import ScoreAggregator
    aggregator = ScoreAggregator()

    # 12. 返回服务
    return RecommendationService(
        repository=repository,
        normalizer=normalizer,
        vector_port=vector_port,
        case_provider=case_provider,
        structured_scorer=structured_scorer,
        business_scorer=business_scorer,
        reranker=reranker,
        aggregator=aggregator,
        config=config,  # 注意：service.py 期望 RetrievalConfig，实际传 AppConfig
    )


def get_retrieval_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendationService:
    """依赖注入：获取 RecommendationService 实例。

    Args:
        session: 数据库会话。

    Returns:
        推荐服务实例。
    """
    config = get_app_config()
    return _build_retrieval_service(session, config)


# =============================================================================
# 请求校验辅助
# =============================================================================


def _validate_retrieval_request(
    request: RetrievalRequest,
    max_top_k: int,
    max_business_weight: float,
) -> list[ValidationErrorDetail]:
    """校验检索请求参数。

    对应 Requirement 1.3：在进入运行记录流水线之前返回 422。

    Args:
        request: 检索请求。
        max_top_k: 配置的最大 Top-K。
        max_business_weight: 配置的最大业务权重。

    Returns:
        字段级错误列表（空表示校验通过）。
    """
    errors: list[ValidationErrorDetail] = []

    # query_text 非空校验（已在 schema 层通过 min_length=1 校验，此处补充空白字符校验）
    if not request.query_text or not request.query_text.strip():
        errors.append(
            ValidationErrorDetail(
                field="query_text",
                message="查询文本不能为空或仅包含空白字符",
            )
        )

    # top_k 越界校验
    if request.top_k <= 0 or request.top_k > max_top_k:
        errors.append(
            ValidationErrorDetail(
                field="top_k",
                message=f"Top-K 必须在 1 到 {max_top_k} 之间",
            )
        )

    # business_weights 范围校验
    if request.business_weights is not None:
        weights = request.business_weights
        if weights.business_type_weight < 0 or weights.business_type_weight > max_business_weight:
            errors.append(
                ValidationErrorDetail(
                    field="business_weights.business_type_weight",
                    message=f"业务权重必须在 0 到 {max_business_weight} 之间",
                )
            )
        if weights.store_tier_weight < 0 or weights.store_tier_weight > max_business_weight:
            errors.append(
                ValidationErrorDetail(
                    field="business_weights.store_tier_weight",
                    message=f"门店等级权重必须在 0 到 {max_business_weight} 之间",
                )
            )
        if weights.brand_affinity_weight < 0 or weights.brand_affinity_weight > max_business_weight:
            errors.append(
                ValidationErrorDetail(
                    field="business_weights.brand_affinity_weight",
                    message=f"品牌亲和度权重必须在 0 到 {max_business_weight} 之间",
                )
            )
        if weights.recency_weight < 0 or weights.recency_weight > max_business_weight:
            errors.append(
                ValidationErrorDetail(
                    field="business_weights.recency_weight",
                    message=f"时间接近度权重必须在 0 到 {max_business_weight} 之间",
                )
            )

    return errors


# =============================================================================
# API 端点
# =============================================================================


@router.post(
    "/api/recommendations/similar-cases",
    response_model=RecommendationResponse,
    responses={
        422: {"model": ValidationErrorResponse, "description": "请求参数校验失败"},
        503: {"model": ErrorResponse, "description": "服务不可用或查询标准化失败"},
    },
)
async def recommend_similar_cases(
    request: RetrievalRequest,
    svc: Annotated[RecommendationService, Depends(get_retrieval_service)],
) -> RecommendationResponse:
    """手动相似案例推荐入口。

    接收当前问题、Top-K、过滤条件和可选业务权重，
    返回相似案例推荐项。

    - **query_text**: 当前问题文本（必填）
    - **top_k**: 推荐数量上限（默认 10，最大 100）
    - **filters**: 可选过滤条件（品牌、门店、问题类型、标签、案例状态、创建时间范围）
    - **business_weights**: 可选业务权重参数

    响应状态：
    - **200**: 成功返回推荐（status: succeeded）
    - **200**: 空推荐列表（status: empty）
    - **200**: 降级状态（status: degraded）
    - **503**: 查询标准化失败（fail closed）
    - **422**: 请求参数校验失败

    Requirements: 1.1, 1.3, 1.4, 1.5, 5.1, 7.2
    """
    config = get_app_config()

    # 1. Request-level 校验（对应 Requirement 1.3）
    #    返回 422，不创建推荐运行记录
    validation_errors = _validate_retrieval_request(
        request,
        max_top_k=config.max_top_k,
        max_business_weight=config.max_business_weight,
    )
    if validation_errors:
        logger.warning(
            "检索请求校验失败: errors=%s",
            [(e.field, e.message) for e in validation_errors],
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ValidationErrorResponse(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="请求参数验证失败",
                details=validation_errors,
            ).model_dump(),
        )

    # 2. 禁用检查
    if not config.retrieval_enabled:
        logger.warning("检索推荐功能未启用")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=ErrorCode.RETRIEVAL_DISABLED,
                message="案例推荐检索功能未启用",
            ).model_dump(),
        )

    # 3. 调用服务（服务内部处理运行记录创建和终态写入）
    try:
        response = await svc.recommend_similar_cases(request)
        return response
    except Exception as exc:
        # 服务层异常不应直接泄漏给客户端
        logger.exception("推荐服务异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="推荐服务发生内部错误",
            ).model_dump(),
        )


@router.get(
    "/api/recommendations/runs/{run_id}",
    response_model=RecommendationRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "推荐运行不存在"},
    },
)
async def get_recommendation_run(
    run_id: str,
    svc: Annotated[RecommendationService, Depends(get_retrieval_service)],
) -> RecommendationRunResponse:
    """查询推荐运行状态和候选快照元数据。

    返回推荐运行状态和候选快照元数据（含 contract_version），
    不返回完整查询原文或完整案例正文。

    - **run_id**: 推荐运行标识（UUID 格式）

    返回：
    - **200**: 成功返回运行状态和推荐项快照
    - **404**: 运行不存在

    Requirements: 7.2
    """
    response = await svc.get_run(run_id)

    if response is None:
        logger.info("推荐运行不存在: run_id=%s", run_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=ErrorCode.CASE_NOT_FOUND,
                message=f"推荐运行不存在: run_id={run_id}",
            ).model_dump(),
        )

    return response
