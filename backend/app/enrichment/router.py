"""案例增强 API 路由。

暴露创建增强运行、查询当前增强状态、删除派生数据和重试运行端点。

Responsibilities:
- 创建增强运行和重试端点委托 EnrichmentJobRunner 执行
- 删除端点委托 EnrichmentService.delete_enrichment_data 执行
- 查询端点通过 EnrichmentRepository 读取状态
- 错误响应沿用上游统一结构

Requirements: 1.1, 1.2, 1.3, 1.4, 4.4, 4.5, 6.4, 7.1, 7.3, 7.5
Boundary: EnrichmentRouter
"""
import logging
import time
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, status

if TYPE_CHECKING:
    from app.enrichment.jobs import EnrichmentJobRunner
    from app.enrichment.recommendation_copy import RecommendationCopyService
    from app.enrichment.service import EnrichmentService

from app.core.errors import ErrorCode, ErrorResponse, ErrorMapper, create_error_response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.enrichment.schemas import (
    CaseEnrichmentResultResponse,
    CaseEnrichmentStatusResponse,
    CreateEnrichmentRunRequest,
    DeleteEnrichmentRequest,
    DeleteEnrichmentResponse,
    EnrichmentRunResponse,
    MissingInformationItem,
    RecommendationCopyRequest,
    RecommendationCopyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["enrichment"])


def get_enrichment_job_runner(
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """获取 EnrichmentJobRunner 实例。

    构造完整的依赖链:
    Router -> JobRunner -> Service -> LLMClient/PromptCatalog/Validator/Repository。

    Args:
        session: 数据库会话

    Returns:
        EnrichmentJobRunner: 增强运行生命周期管理器
    """
    from app.core.llm_client import LLMClient
    from app.core.config import get_app_config
    from app.enrichment.case_snapshot import CaseSnapshotProvider
    from app.enrichment.jobs import EnrichmentJobRunner
    from app.enrichment.prompts import PromptCatalog
    from app.enrichment.repository import EnrichmentRepository
    from app.enrichment.service import EnrichmentService
    from app.enrichment.validators import OutputValidator

    config = get_app_config()

    repository = EnrichmentRepository(session)
    llm_client = LLMClient(config.enrichment_llm)
    prompt_catalog = PromptCatalog()
    validator = OutputValidator()

    enrichment_service = EnrichmentService(
        llm_client=llm_client,
        prompt_catalog=prompt_catalog,
        validator=validator,
        repository=repository,
        config=config.enrichment_llm,
    )

    # 构造 CaseSnapshotProvider（依赖 CaseService）
    from app.cases.repository import CaseRepository
    from app.cases.service import CaseService
    from app.cases.validators import CaseValidator

    case_repository = CaseRepository(session)
    case_validator = CaseValidator()
    case_service = CaseService(case_repository, case_validator, repository)
    case_provider = CaseSnapshotProvider(case_service)

    return EnrichmentJobRunner(
        enrichment_service=enrichment_service,
        case_provider=case_provider,
        repository=repository,
        config=config.enrichment_llm,
    )


def get_enrichment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """获取 EnrichmentService 实例。

    用于删除端点，不经过 JobRunner。

    Args:
        session: 数据库会话

    Returns:
        EnrichmentService: 增强服务实例
    """
    from app.core.llm_client import LLMClient
    from app.core.config import get_app_config
    from app.enrichment.prompts import PromptCatalog
    from app.enrichment.repository import EnrichmentRepository
    from app.enrichment.service import EnrichmentService
    from app.enrichment.validators import OutputValidator

    config = get_app_config()

    repository = EnrichmentRepository(session)
    llm_client = LLMClient(config.enrichment_llm)
    prompt_catalog = PromptCatalog()
    validator = OutputValidator()

    return EnrichmentService(
        llm_client=llm_client,
        prompt_catalog=prompt_catalog,
        validator=validator,
        repository=repository,
        config=config.enrichment_llm,
    )


def get_recommendation_copy_service(
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """获取 RecommendationCopyService 实例。

    构造推荐文案服务的依赖链:
    Router -> RecommendationCopyService -> LLMClient/PromptCatalog/Validator/Repository。

    Args:
        session: 数据库会话

    Returns:
        RecommendationCopyService: 推荐文案服务实例
    """
    from app.core.llm_client import LLMClient
    from app.core.config import get_app_config
    from app.enrichment.prompts import PromptCatalog
    from app.enrichment.recommendation_copy import RecommendationCopyService
    from app.enrichment.repository import EnrichmentRepository
    from app.enrichment.validators import OutputValidator

    config = get_app_config()

    repository = EnrichmentRepository(session)
    llm_client = LLMClient(config.enrichment_llm)
    prompt_catalog = PromptCatalog()
    validator = OutputValidator()

    return RecommendationCopyService(
        llm_client=llm_client,
        prompt_catalog=prompt_catalog,
        validator=validator,
        repository=repository,
        config=config.enrichment_llm,
    )


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post(
    "/api/a3-cases/{case_id}/enrichment-runs",
    response_model=EnrichmentRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "案例未找到"},
        409: {"model": ErrorResponse, "description": "状态冲突"},
        422: {"model": ErrorResponse, "description": "校验失败"},
        503: {"model": ErrorResponse, "description": "LLM 供应商错误"},
    },
    summary="创建增强运行",
    description="为指定案例触发 LLM 增强运行，立即返回运行状态。",
)
async def create_enrichment_run(
    case_id: str,
    request: CreateEnrichmentRunRequest,
    job_runner: Annotated[
        "EnrichmentJobRunner", Depends(get_enrichment_job_runner)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EnrichmentRunResponse:
    """创建增强运行。

    委托 EnrichmentJobRunner 执行。JobRunner 内部已处理所有错误，
    始终返回 EnrichmentRunResponse（含 run_id 和状态）。

    Args:
        case_id: 案例标识
        request: 创建增强运行请求
        job_runner: 增强运行生命周期管理器
        session: 与 JobRunner 内仓储共享的请求级会话（见下述 commit）。

    Returns:
        EnrichmentRunResponse: 增强运行响应

    Note:
        在返回前显式 ``commit``：与 ``vector_indexing`` 路由一致，避免 FastAPI
        对 ``yield`` 型 ``get_db`` 的 teardown 在响应送达后才提交事务，客户端
        紧接着 GET ``/enrichment`` 时读不到刚写入的运行与派生结果。
    """
    t0 = time.perf_counter()
    response = await job_runner.run_enrichment(case_id, request)
    total_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "创建增强运行 API 总耗时: case_id=%s, run_id=%s, status=%s, total_ms=%.1f",
        case_id,
        response.run_id,
        response.status,
        total_ms,
    )
    await session.commit()
    return response


@router.get(
    "/api/a3-cases/{case_id}/enrichment",
    response_model=CaseEnrichmentStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "案例未找到"},
    },
    summary="查询当前增强状态",
    description="返回指定案例的最新增强运行记录和当前有效派生结果。",
)
async def get_enrichment_status(
    case_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CaseEnrichmentStatusResponse:
    """查询当前增强状态。

    通过 EnrichmentRepository 查询最新增强运行和当前有效派生结果。

    Args:
        case_id: 案例标识
        session: 数据库会话

    Returns:
        CaseEnrichmentStatusResponse: 增强状态响应
    """
    from app.enrichment.repository import EnrichmentRepository

    repository = EnrichmentRepository(session)

    latest_run_orm = await repository.get_latest_run(case_id)
    current_result_orm = await repository.get_current_result(case_id)

    latest_run = (
        EnrichmentRunResponse.model_validate(latest_run_orm)
        if latest_run_orm
        else None
    )

    current_result = None
    if current_result_orm:
        current_result = _build_result_response(current_result_orm)

    return CaseEnrichmentStatusResponse(
        case_id=case_id,
        latest_run=latest_run,
        current_result=current_result,
    )


@router.post(
    "/api/enrichment/delete",
    response_model=DeleteEnrichmentResponse,
    responses={
        422: {"model": ErrorResponse, "description": "校验失败"},
        500: {"model": ErrorResponse, "description": "删除失败"},
    },
    summary="删除增强派生数据",
    description=(
        "删除指定案例或增强标识的所有派生数据。"
        "幂等操作，对不存在的派生数据返回 deleted_count: 0。"
    ),
)
async def delete_enrichment(
    request: DeleteEnrichmentRequest,
    service: Annotated[
        "EnrichmentService", Depends(get_enrichment_service)
    ],
) -> DeleteEnrichmentResponse:
    """删除增强派生数据。

    在单个事务内删除派生结果和运行记录。
    对不存在的派生数据返回 deleted_count: 0（幂等）。

    Args:
        request: 删除请求
        service: 增强服务实例

    Returns:
        DeleteEnrichmentResponse: 删除响应

    Raises:
        HTTPException: 参数校验失败 (422) 或删除失败 (500)
    """
    try:
        result = await service.delete_enrichment_data(
            case_id=request.case_id,
            enrichment_id=request.enrichment_id,
        )
        return DeleteEnrichmentResponse(
            success=result.success,
            deleted_count=result.deleted_count,
            deleted_at=result.deleted_at,
        )
    except ValueError as exc:
        logger.warning(f"删除参数校验失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message=str(exc),
            ).model_dump(),
        )
    except Exception as exc:
        logger.error(f"删除增强数据失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to delete enrichment data",
            ).model_dump(),
        )


@router.post(
    "/api/enrichment-runs/{run_id}/retry",
    response_model=EnrichmentRunResponse,
    responses={
        404: {"model": ErrorResponse, "description": "运行不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"},
        503: {"model": ErrorResponse, "description": "LLM 供应商错误"},
    },
    summary="重试增强运行",
    description="对可重试的失败增强运行执行重试，返回新运行记录。",
)
async def retry_enrichment_run(
    run_id: str,
    job_runner: Annotated[
        "EnrichmentJobRunner", Depends(get_enrichment_job_runner)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EnrichmentRunResponse:
    """重试增强运行。

    仅允许 retryable 状态的运行进行重试。
    创建新的运行记录并重新执行增强。

    Args:
        run_id: 待重试的运行标识
        job_runner: 增强运行生命周期管理器
        session: 与 JobRunner 内仓储共享的请求级会话。

    Returns:
        EnrichmentRunResponse: 新运行的增强运行响应

    Raises:
        HTTPException: 运行不存在 (404) 或状态不允许重试 (409)

    Note:
        返回前显式 ``commit``，理由同 ``create_enrichment_run``。
    """
    try:
        response = await job_runner.retry_run(run_id)
    except ValueError as exc:
        error_msg = str(exc)
        if "不存在" in error_msg:
            logger.warning(f"重试目标运行不存在: {run_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=create_error_response(
                    code=ErrorCode.ENRICHMENT_RUN_NOT_FOUND,
                    message=error_msg,
                ).model_dump(),
            )
        logger.warning(f"重试状态不允许: {run_id}, {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=create_error_response(
                code=ErrorCode.ENRICHMENT_RETRY_NOT_ALLOWED,
                message=error_msg,
            ).model_dump(),
        )
    await session.commit()
    return response


@router.post(
    "/api/recommendations/copy",
    response_model=RecommendationCopyResponse,
    responses={
        503: {"model": ErrorResponse, "description": "LLM 调用或校验失败"},
    },
    summary="生成推荐文案",
    description=(
        "为已排序的推荐候选案例生成解释文案。"
        "响应按输入候选顺序返回推荐理由、可参考解决点和注意事项。"
        "不包含排序或相似度修改字段。"
    ),
)
async def generate_recommendation_copy(
    request: RecommendationCopyRequest,
    service: Annotated[
        "RecommendationCopyService", Depends(get_recommendation_copy_service)
    ],
) -> RecommendationCopyResponse:
    """生成推荐文案。

    委托 RecommendationCopyService 执行。
    LLM 调用失败或校验失败时返回 HTTP 503。
    响应按输入候选顺序返回解释文案，不包含排序或相似度修改字段。

    Args:
        request: 推荐文案请求，含当前问题和已排序候选列表
        service: 推荐文案服务实例

    Returns:
        RecommendationCopyResponse: 推荐文案响应

    Raises:
        HTTPException: LLM 调用或校验失败时返回 503
    """
    try:
        return await service.generate_copy(request)
    except Exception as exc:
        raise ErrorMapper().to_http_exception(exc)


# ---------------------------------------------------------------------------
# 内部辅助方法
# ---------------------------------------------------------------------------


def _build_result_response(result_orm) -> CaseEnrichmentResultResponse:
    """从 ORM 对象构建 CaseEnrichmentResultResponse。

    手动映射字段，避免 from_attributes 模式下 ORM
    缺少 missing_information 字段导致校验失败。

    Args:
        result_orm: CaseEnrichmentResult ORM 对象

    Returns:
        CaseEnrichmentResultResponse: 派生结果响应
    """
    missing_info_raw = getattr(result_orm, "missing_information", None)
    missing_info = (
        [MissingInformationItem.model_validate(item) for item in missing_info_raw]
        if missing_info_raw
        else []
    )

    return CaseEnrichmentResultResponse(
        enrichment_id=result_orm.enrichment_id,
        case_id=result_orm.case_id,
        case_updated_at=result_orm.case_updated_at,
        status=result_orm.status,
        problem_summary=result_orm.problem_summary,
        solution_summary=result_orm.solution_summary,
        structured_suggestions=result_orm.structured_suggestions,
        tag_suggestions=result_orm.tag_suggestions,
        source_references=result_orm.source_references,
        missing_information=missing_info,
        output_version=result_orm.output_version,
        created_at=result_orm.created_at,
        updated_at=result_orm.updated_at,
    )
