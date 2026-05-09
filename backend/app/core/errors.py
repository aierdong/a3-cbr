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

    # --- LLM 增强相关错误码 ---

    # 案例增强资源错误 (404/409)
    ENRICHMENT_RUN_NOT_FOUND = "ENRICHMENT_RUN_NOT_FOUND"  # 404: 增强运行不存在
    ENRICHMENT_STATE_CONFLICT = "ENRICHMENT_STATE_CONFLICT"  # 409: 案例状态不可增强（如 draft）
    ENRICHMENT_RETRY_NOT_FOUND = "ENRICHMENT_RETRY_NOT_FOUND"  # 404: 重试目标运行不存在
    ENRICHMENT_RETRY_NOT_ALLOWED = "ENRICHMENT_RETRY_NOT_ALLOWED"  # 409: 当前状态不允许重试

    # Prompt 注入检测
    INJECTION_RISK_DETECTED = "INJECTION_RISK_DETECTED"  # 200: 高风险注入模式，阻断请求
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"  # 校验阶段: 输出侧注入嫌疑

    # LLM 供应商错误 (503)
    LLM_TIMEOUT = "LLM_TIMEOUT"  # 503: LLM 调用超时
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"  # 503: LLM 限流
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"  # 503: 供应商故障
    LLM_PRIVACY_CONFIG_MISSING = "LLM_PRIVACY_CONFIG_MISSING"  # 503: 隐私配置缺失
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"  # 503: LLM 输出无法解析或校验失败


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