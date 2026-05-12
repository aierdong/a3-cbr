/**
 * useAsyncState Composable
 *
 * 统一管理异步请求状态（loading、data、error）
 * 遵循 design.md § useAsyncState 和 requirements.md § 6.2（状态可观察）
 */

import { ref, computed, type Ref } from 'vue';
import type { ApiError, ApiResult } from '../api/errors';

/**
 * 异步状态阶段
 */
export type AsyncPhase = 'idle' | 'loading' | 'success' | 'empty' | 'error';

/**
 * 成功变体（用于区分完整成功和降级成功）
 */
export type SuccessVariant = 'complete' | 'degraded' | null;

/**
 * useAsyncState 配置选项
 */
export interface UseAsyncStateOptions<T> {
  isEmpty?: (data: T) => boolean;
  isDegradedSuccess?: (data: T) => boolean;
}

/**
 * useAsyncState 返回类型
 */
export interface UseAsyncStateReturn<T> {
  phase: Ref<AsyncPhase>;
  data: Ref<T | null>;
  apiError: Ref<ApiError | null>;
  errorKind: Ref<string | null>;
  successVariant: Ref<SuccessVariant>;
  run: (fn: () => Promise<ApiResult<T>>) => Promise<void>;
  reset: () => void;
}

/**
 * 默认判断数据是否为空
 */
function defaultIsEmpty(data: unknown): boolean {
  if (data === null || data === undefined) return true;
  if (Array.isArray(data)) return data.length === 0;
  if (typeof data === 'object') return Object.keys(data).length === 0;
  return false;
}

/**
 * 创建异步状态管理 composable
 *
 * @param options - 配置选项
 * @returns 异步状态和操作方法
 *
 * @example
 * ```ts
 * const { phase, data, apiError, run } = useAsyncState<User>();
 *
 * async function loadUser() {
 *   await run(async () => {
 *     return await apiClient.get('/users/1');
 *   });
 * }
 * ```
 */
export function useAsyncState<T>(options: UseAsyncStateOptions<T> = {}): UseAsyncStateReturn<T> {
  const { isEmpty = defaultIsEmpty, isDegradedSuccess } = options;

  const phase = ref<AsyncPhase>('idle');
  const data = ref<T | null>(null) as Ref<T | null>;
  const apiError = ref<ApiError | null>(null);
  const successVariant = ref<SuccessVariant>(null);

  const errorKind = computed(() => apiError.value?.kind ?? null);

  /**
   * 执行异步操作
   */
  async function run(fn: () => Promise<ApiResult<T>>): Promise<void> {
    phase.value = 'loading';
    apiError.value = null;
    successVariant.value = null;

    try {
      const result = await fn();

      if (result.ok) {
        data.value = result.data;

        // 检查是否为降级成功
        if (isDegradedSuccess && isDegradedSuccess(result.data)) {
          phase.value = 'success';
          successVariant.value = 'degraded';
        }
        // 检查是否为空结果
        else if (isEmpty(result.data)) {
          phase.value = 'empty';
          successVariant.value = 'complete';
        }
        // 完整成功
        else {
          phase.value = 'success';
          successVariant.value = 'complete';
        }
      } else {
        apiError.value = result.error;
        phase.value = 'error';
      }
    } catch (err) {
      // 处理意外异常
      apiError.value = {
        kind: 'unknown',
        code: 'UNEXPECTED_ERROR',
        message: err instanceof Error ? err.message : '未知错误',
        status: 0,
      };
      phase.value = 'error';
    }
  }

  /**
   * 重置状态
   */
  function reset(): void {
    phase.value = 'idle';
    data.value = null;
    apiError.value = null;
    successVariant.value = null;
  }

  return {
    phase,
    data,
    apiError,
    errorKind,
    successVariant,
    run,
    reset,
  };
}
