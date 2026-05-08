"""案例管理 API 路由。

暴露创建、编辑、删除（基础删除和级联删除）、详情、列表查询端点。

Responsibilities:
- 接收请求并调用 CaseService，不直接访问数据库
- 使用 CaseSchemas 固定请求和响应结构
- 将领域错误映射为一致 HTTP 错误响应
- 删除操作支持任意状态的案例，无状态前置校验
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.cases.coordinator import CaseDeleteCoordinator
from app.cases.schemas import (
    CascadeDeleteRequest,
    CascadeDeleteResponse,
    CaseDetailResponse,
    CreateCaseRequest,
    DeleteCaseRequest,
    DeleteCaseResponse,
    UpdateCaseRequest,
)
from app.cases.service import (
    CaseNotFoundError,
    CaseService,
    CaseStateConflictError,
    CaseValidationError,
    StoreNotFoundError,
)
from app.core.errors import ErrorCode, ErrorDetail, ErrorResponse, create_error_response
from app.db.session import AsyncSession, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/a3-cases", tags=["cases"])


def get_case_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CaseService:
    """获取 CaseService 实例。

    Args:
        session: 数据库会话

    Returns:
        CaseService: 案例服务实例
    """
    from app.cases.repository import CaseRepository
    from app.cases.validators import CaseValidator

    repository = CaseRepository(session)
    validator = CaseValidator()
    return CaseService(repository, validator)


def get_case_delete_coordinator(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CaseDeleteCoordinator:
    """获取 CaseDeleteCoordinator 实例。

    Args:
        session: 数据库会话

    Returns:
        CaseDeleteCoordinator: 级联删除协调器实例
    """
    from app.cases.repository import CaseRepository
    from app.cases.validators import CaseValidator

    repository = CaseRepository(session)
    validator = CaseValidator()
    service = CaseService(repository, validator)
    return CaseDeleteCoordinator(service)


@router.post(
    "",
    response_model=CaseDetailResponse,
    responses={
        422: {"model": ErrorResponse, "description": "校验失败"},
        500: {"model": ErrorResponse, "description": "系统错误"},
    },
    summary="创建 A3 案例",
    description="创建新案例，成功时返回案例标识、基础状态和创建时间。",
)
async def create_case(
    request: CreateCaseRequest,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseDetailResponse:
    """创建新案例。

    Args:
        request: 创建案例请求
        service: 案例服务实例

    Returns:
        CaseDetailResponse: 创建的案例详情

    Raises:
        HTTPException: 校验失败或系统错误
    """
    try:
        return await service.create_case(request)
    except CaseValidationError as e:
        logger.warning(f"Case validation failed: {e.errors}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message="Case validation failed",
                fields=[
                    ErrorDetail(field=err.field, message=err.message)
                    for err in e.errors
                ],
            ).model_dump(),
        )
    except StoreNotFoundError as e:
        logger.warning(f"Store not found: {e.store_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=create_error_response(
                code=ErrorCode.STORE_NOT_FOUND,
                message=f"store_id '{e.store_id}' does not exist in store_infos",
            ).model_dump(),
        )
    except Exception as e:
        logger.error(f"Unexpected error during case creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="An internal error occurred",
            ).model_dump(),
        )


@router.put(
    "/{case_id}",
    response_model=CaseDetailResponse,
    responses={
        404: {"model": ErrorResponse, "description": "案例未找到"},
        409: {"model": ErrorResponse, "description": "状态冲突"},
        422: {"model": ErrorResponse, "description": "校验失败"},
        500: {"model": ErrorResponse, "description": "系统错误"},
    },
    summary="编辑 A3 案例",
    description="编辑案例，成功时返回更新后的核心字段和更新时间。",
)
async def update_case(
    case_id: str,
    request: UpdateCaseRequest,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseDetailResponse:
    """编辑案例。

    Args:
        case_id: 案例标识
        request: 更新案例请求
        service: 案例服务实例

    Returns:
        CaseDetailResponse: 更新后的案例详情

    Raises:
        HTTPException: 案例未找到、状态冲突、校验失败或系统错误
    """
    try:
        return await service.update_case(case_id, request)
    except CaseNotFoundError:
        logger.warning(f"Case not found during update: {case_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=ErrorCode.CASE_NOT_FOUND,
                message=f"case_id '{case_id}' not found",
            ).model_dump(),
        )
    except CaseStateConflictError as e:
        logger.warning(f"Case state conflict during update: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=create_error_response(
                code=ErrorCode.CASE_STATE_CONFLICT,
                message=e.message,
                meta={"current_status": e.current_status},
            ).model_dump(),
        )
    except CaseValidationError as e:
        logger.warning(f"Case validation failed: {e.errors}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message="Case validation failed",
                fields=[
                    ErrorDetail(field=err.field, message=err.message)
                    for err in e.errors
                ],
            ).model_dump(),
        )
    except StoreNotFoundError as e:
        logger.warning(f"Store not found during update: {e.store_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=create_error_response(
                code=ErrorCode.STORE_NOT_FOUND,
                message=f"store_id '{e.store_id}' does not exist in store_infos",
            ).model_dump(),
        )
    except Exception as e:
        logger.error(f"Unexpected error during case update: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="An internal error occurred",
            ).model_dump(),
        )


@router.post(
    "/delete",
    response_model=DeleteCaseResponse,
    responses={
        404: {"model": ErrorResponse, "description": "案例未找到"},
        422: {"model": ErrorResponse, "description": "校验失败"},
        500: {"model": ErrorResponse, "description": "系统错误"},
    },
    summary="删除 A3 案例",
    description="基础删除接口，接受 DeleteCaseRequest，返回 DeleteCaseResponse。",
)
async def delete_case(
    request: DeleteCaseRequest,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> DeleteCaseResponse:
    """删除案例。

    支持任意状态的案例，无状态前置校验。

    Args:
        request: 删除案例请求
        service: 案例服务实例

    Returns:
        DeleteCaseResponse: 删除响应

    Raises:
        HTTPException: 案例未找到或系统错误
    """
    try:
        return await service.delete_case(request.case_id)
    except CaseNotFoundError:
        logger.warning(f"Case not found during delete: {request.case_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=ErrorCode.CASE_NOT_FOUND,
                message=f"case_id '{request.case_id}' not found",
            ).model_dump(),
        )
    except Exception as e:
        logger.error(f"Unexpected error during case deletion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="An internal error occurred",
            ).model_dump(),
        )


@router.post(
    "/cascade-delete",
    response_model=CascadeDeleteResponse,
    responses={
        404: {"model": ErrorResponse, "description": "案例未找到"},
        422: {"model": ErrorResponse, "description": "校验失败"},
        500: {"model": ErrorResponse, "description": "系统错误"},
    },
    summary="级联删除 A3 案例",
    description="级联删除协调接口，接受 CascadeDeleteRequest，返回 CascadeDeleteResponse。",
)
async def cascade_delete_case(
    request: CascadeDeleteRequest,
    coordinator: Annotated[CaseDeleteCoordinator, Depends(get_case_delete_coordinator)],
) -> CascadeDeleteResponse:
    """执行级联删除。

    依次调用本规格的 CaseService.delete_case 和下游规格的删除 API。
    下游服务不可用或删除失败时，不阻塞上游删除，记录失败信息到 partial_failures。

    Args:
        request: 级联删除请求
        coordinator: 级联删除协调器实例

    Returns:
        CascadeDeleteResponse: 级联删除响应
    """
    try:
        return await coordinator.delete_case_cascade(request)
    except Exception as e:
        logger.error(f"Unexpected error during cascade delete: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="An internal error occurred",
            ).model_dump(),
        )
