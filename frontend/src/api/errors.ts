/**
 * API 错误类型定义
 *
 * 遵循 design.md § Error Handling 和 requirements.md § 6.4（敏感信息保护）
 */

/**
 * 字段级错误
 */
export interface FieldError {
  field: string;      // 字段路径，如 "problem_description", "store_profile.store_id"
  message: string;    // 用户可读错误消息
}

/**
 * API 错误分类
 *
 * 对应 design.md § Error Categories and Responses
 */
export type ApiErrorKind =
  | 'validation'              // 422: 字段校验失败
  | 'user_error'              // 400: 业务错误（如门店不存在）
  | 'not_found'               // 404: 资源不存在
  | 'conflict'                // 409: 状态冲突
  | 'dependency_unavailable'  // 503: 依赖服务不可用
  | 'system'                  // 500: 系统内部错误
  | 'network'                 // 0: 网络错误
  | 'unknown';                // 未知错误

/**
 * API 错误对象
 *
 * 只包含稳定 code、用户可读 message、HTTP status 和可选字段错误
 * 不保存完整后端响应、meta 或敏感信息（对应需求 6.4）
 */
export interface ApiError {
  kind: ApiErrorKind;
  code: string;
  message: string;
  status: number;
  fields?: FieldError[];  // 字段级错误数组（仅 422 validation 错误）
}

/**
 * 后端错误响应结构（用于解析，不暴露给页面）
 */
export interface BackendErrorResponse {
  code: string;
  message: string;
  fields?: FieldError[];
  meta?: unknown;  // 不保存到 ApiError 中
}

/**
 * API 调用结果类型（Result pattern）
 */
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError };
