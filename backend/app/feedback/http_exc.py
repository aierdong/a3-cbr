"""反馈领域异常 → HTTPException（统一 ErrorResponse detail）。"""

from fastapi import HTTPException, status

from app.core.errors import (
    ErrorCode,
    _FEEDBACK_PUBLIC_MESSAGES,
    create_error_response,
)
from app.feedback.exceptions import (
    FeedbackDisabledError,
    FeedbackTargetMismatchError,
    FeedbackTargetNotFoundError,
)


def feedback_exception_to_http(exc: BaseException) -> HTTPException:
    """将反馈模块异常映射为带统一结构的 HTTP 响应。"""
    if isinstance(exc, FeedbackTargetNotFoundError):
        code = ErrorCode.FEEDBACK_TARGET_NOT_FOUND
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code=code,
                message=_FEEDBACK_PUBLIC_MESSAGES[code],
            ).model_dump(),
        )
    if isinstance(exc, FeedbackTargetMismatchError):
        code = ErrorCode.FEEDBACK_TARGET_MISMATCH
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=create_error_response(
                code=code,
                message=_FEEDBACK_PUBLIC_MESSAGES[code],
            ).model_dump(),
        )
    if isinstance(exc, FeedbackDisabledError):
        code = ErrorCode.FEEDBACK_DISABLED
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=code,
                message=_FEEDBACK_PUBLIC_MESSAGES[code],
            ).model_dump(),
        )
    raise exc
