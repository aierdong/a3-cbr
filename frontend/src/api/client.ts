/**
 * API Client 实现
 *
 * 遵循 design.md § ApiClient 和 Error Handling
 * 满足 requirements.md § 1.4, 6.1, 6.2, 6.4
 */

import type { ApiError, ApiErrorKind, ApiResult, BackendErrorResponse } from './errors';

/**
 * API Client 配置
 */
export interface ApiClientConfig {
  baseUrl?: string;
  timeout?: number;
}

/**
 * API Client 接口
 */
export interface ApiClient {
  get<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<ApiResult<T>>;
  post<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>>;
  put<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>>;
}

/**
 * 根据 HTTP 状态码映射错误分类
 *
 * 对应 design.md § Error Mapping Rules
 */
function mapStatusToErrorKind(status: number): ApiErrorKind {
  switch (status) {
    case 422:
      return 'validation';
    case 400:
      return 'user_error';
    case 404:
      return 'not_found';
    case 409:
      return 'conflict';
    case 503:
      return 'dependency_unavailable';
    case 500:
      return 'system';
    case 0:
      return 'network';
    default:
      return 'unknown';
  }
}

/**
 * 解析后端错误响应并映射为前端 ApiError
 *
 * 遵循错误脱敏规则（需求 6.4）：
 * - 只保留 code、message、status、fields
 * - 不保存 meta 或完整后端响应
 */
async function parseErrorResponse(response: Response): Promise<ApiError> {
  const status = response.status;
  const kind = mapStatusToErrorKind(status);

  try {
    const body = await response.json() as BackendErrorResponse;

    return {
      kind,
      code: body.code || 'UNKNOWN_ERROR',
      message: body.message || '未知错误',
      status,
      // 只在 422 validation 错误时包含字段错误
      ...(kind === 'validation' && body.fields ? { fields: body.fields } : {}),
    };
  } catch {
    // 无法解析 JSON 响应
    return {
      kind,
      code: 'UNKNOWN_ERROR',
      message: '服务器响应格式错误',
      status,
    };
  }
}

/**
 * 构建查询字符串
 */
function buildQueryString(query?: Record<string, string | number | boolean | undefined>): string {
  if (!query) return '';

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) {
      params.append(key, String(value));
    }
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * 创建 API Client 实例
 *
 * @param config - 配置选项
 * @returns API Client 实例
 */
export function createApiClient(config: ApiClientConfig = {}): ApiClient {
  const baseUrl = config.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '';
  const timeout = config.timeout ?? 30000;

  /**
   * 执行 HTTP 请求
   */
  async function request<T>(
    method: 'GET' | 'POST' | 'PUT',
    path: string,
    options: {
      query?: Record<string, string | number | boolean | undefined>;
      body?: unknown;
    } = {}
  ): Promise<ApiResult<T>> {
    const url = `${baseUrl}${path}${buildQueryString(options.query)}`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(url, {
        method,
        headers: {
          'Accept': 'application/json',
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const error = await parseErrorResponse(response);
        return { ok: false, error };
      }

      const data = await response.json() as T;
      return { ok: true, data };

    } catch (err) {
      clearTimeout(timeoutId);

      // 网络错误或超时
      return {
        ok: false,
        error: {
          kind: 'network',
          code: 'NETWORK_ERROR',
          message: err instanceof Error ? err.message : '网络请求失败',
          status: 0,
        },
      };
    }
  }

  return {
    get<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<ApiResult<T>> {
      return request<T>('GET', path, { query });
    },

    post<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>> {
      return request<TResponse>('POST', path, { body });
    },

    put<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>> {
      return request<TResponse>('PUT', path, { body });
    },
  };
}
