"""向量索引与语义搜索 API 路由。

暴露手动刷新、状态查询、级联删除、任务重试与 Top-K 搜索端点。

Requirements: 3.3, 4.1, 4.3, 5.1, 6.3
Boundary: VectorRouter
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.repository import CaseRepository
from app.cases.service import CaseService
from app.cases.validators import CaseValidator
from app.core.llm_client import LLMClientError
from app.core.config import get_app_config
from app.core.errors import (
    ErrorCode,
    ErrorDetail,
    ErrorMapper,
    ErrorResponse,
    create_error_response,
)
from app.db.session import get_db
from app.enrichment.repository import EnrichmentRepository
from app.vector_indexing.embedding_client import EmbeddingClient
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.index_service import VectorIndexService
from app.vector_indexing.job_runner import (
    VectorIndexJobNotFoundError,
    VectorJobRetryNotAllowedError,
    VectorJobRunner,
)
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.schemas import (
    DeleteVectorIndexRequest,
    DeleteVectorIndexResponse,
    RefreshVectorIndexRequest,
    VectorIndexJobResponse,
    VectorIndexStatusResponse,
    VectorSearchRequest,
    VectorSearchResponse,
)
from app.vector_indexing.search import VectorSearchService, VectorSearchValidationError
from app.vector_indexing.source_provider import CaseIndexSourceProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vector-indexing"])

_MANUAL_RETRY_CAP = 3


def _build_vector_index_stack(
    session: AsyncSession,
) -> tuple[VectorIndexService, VectorJobRunner]:
    config = get_app_config()
    case_repository = CaseRepository(session)
    case_validator = CaseValidator()
    enrichment_repository = EnrichmentRepository(session)
    case_service = CaseService(
        case_repository, case_validator, enrichment_repository
    )
    source_provider = CaseIndexSourceProvider(case_service, enrichment_repository)
    composer = EmbeddingInputComposer()
    embedding_client = EmbeddingClient(config.embedding)
    index_service = VectorIndexService(
        session,
        source_provider=source_provider,
        composer=composer,
        embedding_client=embedding_client,
    )
    runner = VectorJobRunner(
        session,
        index_service,
        max_manual_retries=_MANUAL_RETRY_CAP,
    )
    index_service.register_job_runner(runner)
    return index_service, runner


def get_vector_index_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VectorIndexService:
    """构造 ``VectorIndexService`` 并注册 ``VectorJobRunner``。

    Args:
        session: 数据库会话。

    Returns:
        配置完成的向量索引编排服务。
    """
    svc, _runner = _build_vector_index_stack(session)
    return svc


def get_vector_job_runner(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VectorJobRunner:
    """构造与索引服务串联的 ``VectorJobRunner``。

    Args:
        session: 数据库会话。

    Returns:
        向量索引任务重试编排器。
    """
    _svc, runner = _build_vector_index_stack(session)
    return runner


def get_vector_search_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VectorSearchService:
    """构造注入仓储的 ``VectorSearchService``。

    Args:
        session: 数据库会话。

    Returns:
        向量搜索服务实例。
    """
    config = get_app_config()
    composer = EmbeddingInputComposer()
    embedding_client = EmbeddingClient(config.embedding)
    repo = VectorRepository(session)
    return VectorSearchService(
        composer,
        embedding_client,
        repository=repo,
    )


@router.post(
    "/api/a3-cases/{case_id}/vector-index/refresh",
    response_model=VectorIndexJobResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def refresh_case_vector_index(
    case_id: str,
    request: RefreshVectorIndexRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    svc: Annotated[VectorIndexService, Depends(get_vector_index_service)],
) -> VectorIndexJobResponse:
    """同步执行案例向量刷新并返回任务终态。

    Args:
        case_id: 案例标识。
        request: 刷新请求体。
        session: 请求级数据库会话（与 svc 共享同一实例）。
        svc: 向量索引服务。

    Returns:
        向量索引任务响应。

    Note:
        在返回前显式 ``commit``：FastAPI 对 ``yield`` 型依赖的 teardown（含 ``get_db`` 内
        的 commit）可能在响应已送达客户端之后才执行，客户端立即 GET 状态时会读不到
        刚写入的向量与任务行（见 fastapi#3620）。
    """
    try:
        result = await svc.refresh_case_index(case_id, request)
    except LLMClientError as exc:
        raise ErrorMapper().to_http_exception(exc)
    except RuntimeError as exc:
        logger.exception("向量索引刷新失败: case_id=%s", case_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=str(exc),
            ).model_dump(),
        )
    await session.commit()
    return result


@router.get(
    "/api/a3-cases/{case_id}/vector-index",
    response_model=VectorIndexStatusResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def get_case_vector_index_status(
    case_id: str,
    svc: Annotated[VectorIndexService, Depends(get_vector_index_service)],
) -> VectorIndexStatusResponse:
    """查询指定案例的向量索引聚合状态。

    Args:
        case_id: 案例标识。
        svc: 向量索引服务。

    Returns:
        状态快照响应。
    """
    try:
        return await svc.get_case_status(case_id)
    except RuntimeError as exc:
        logger.exception("向量索引状态查询失败: case_id=%s", case_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=str(exc),
            ).model_dump(),
        )


@router.post(
    "/api/vector-index/delete",
    response_model=DeleteVectorIndexResponse,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def delete_case_vectors(
    request: DeleteVectorIndexRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    svc: Annotated[VectorIndexService, Depends(get_vector_index_service)],
) -> DeleteVectorIndexResponse:
    """按案例或向量标识删除索引（幂等）。

    Args:
        request: 删除请求。
        session: 请求级数据库会话（与 svc 共享同一实例）。
        svc: 向量索引服务。

    Returns:
        删除结果。
    """
    try:
        result = await svc.delete_case_vector(request)
    except ValueError as exc:
        logger.warning("删除向量索引参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message=str(exc),
            ).model_dump(),
        )
    except RuntimeError as exc:
        logger.exception("删除向量索引失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=str(exc),
            ).model_dump(),
        )
    await session.commit()
    return result


@router.post(
    "/api/vector-index/jobs/{job_id}/retry",
    response_model=VectorIndexJobResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def retry_vector_index_job(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    runner: Annotated[VectorJobRunner, Depends(get_vector_job_runner)],
) -> VectorIndexJobResponse:
    """对可重试的失败任务发起强制刷新重试。

    Args:
        job_id: 历史任务标识。
        session: 请求级数据库会话（与 runner 共享同一实例）。
        runner: 向量任务编排器。

    Returns:
        新刷新任务响应。
    """
    try:
        result = await runner.retry_job(job_id)
    except VectorIndexJobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=ErrorCode.VECTOR_JOB_NOT_FOUND,
                message=f"vector index job not found: {job_id}",
            ).model_dump(),
        )
    except VectorJobRetryNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=create_error_response(
                code=exc.error_code,
                message="vector index job retry not allowed",
            ).model_dump(),
        )
    except LLMClientError as exc:
        raise ErrorMapper().to_http_exception(exc)
    except RuntimeError as exc:
        logger.exception("向量索引任务重试失败: job_id=%s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=str(exc),
            ).model_dump(),
        )
    await session.commit()
    return result


@router.post(
    "/api/vector-search",
    response_model=VectorSearchResponse,
    responses={
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def search_case_vectors(
    request: VectorSearchRequest,
    search_svc: Annotated[VectorSearchService, Depends(get_vector_search_service)],
) -> VectorSearchResponse:
    """按问题语义检索 Top-K 向量候选。

    Args:
        request: 搜索请求。
        search_svc: 向量搜索服务。

    Returns:
        候选列表与查询元数据。
    """
    try:
        return await search_svc.search(request)
    except VectorSearchValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message=exc.message,
                fields=[
                    ErrorDetail(field=exc.field, message=exc.message),
                ],
            ).model_dump(),
        )
    except LLMClientError as exc:
        raise ErrorMapper().to_http_exception(exc)
    except RuntimeError as exc:
        logger.exception("向量搜索失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message=str(exc),
            ).model_dump(),
        )
