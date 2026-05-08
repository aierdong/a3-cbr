"""统一错误响应定义。.

定义 A3 案例管理系统的错误码和错误结构。
"""
from typing import Optional

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """字段级错误详情。."""

    field: str
    message: str


class ErrorResponse(BaseModel):
    """统一错误响应结构。."""

    code: str
    message: str
    fields: list[ErrorDetail] = []
    meta: dict = {}


# 错误码定义
class ErrorCode:
    """错误码常量。."""

    # 校验错误 (422)
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 资源未找到
    STORE_NOT_FOUND = "STORE_NOT_FOUND"  # 400: store_id 在 store_infos 中不存在
    CASE_NOT_FOUND = "CASE_NOT_FOUND"  # 404: case_id 不存在

    # 状态冲突 (409)
    CASE_STATE_CONFLICT = "CASE_STATE_CONFLICT"

    # 系统错误 (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"


def create_error_response(
    code: str,
    message: str,
    fields: Optional[list[ErrorDetail]] = None,
    meta: Optional[dict] = None,
) -> ErrorResponse:
    """创建错误响应。."""
    return ErrorResponse(
        code=code,
        message=message,
        fields=fields or [],
        meta=meta or {},
    )