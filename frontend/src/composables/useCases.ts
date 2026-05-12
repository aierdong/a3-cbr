/**
 * 案例领域 composable：列表筛选与 Keyset 分页（design.md § useCases、CaseApiService）
 */

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type {
  CaseApiService,
  CaseListItem,
  CaseListQuery,
  PaginatedCaseListResponse,
} from '../api/cases'
import type { ApiError } from '../api/errors'

const DEFAULT_LIMIT = 20

export type CaseListPhase = 'idle' | 'loading' | 'success' | 'empty' | 'error'

/** 列表筛选草稿（UI）；创建时间使用 ISO 字符串，由输入控件转换 */
export interface CaseListFilters {
  brand_id?: string
  store_id?: string
  problem_type?: CaseListQuery['problem_type']
  status?: CaseListQuery['status']
  /** 契约尚未支持服务端标签筛选；保留字段供后续扩展 */
  tags?: string
  created_from?: string
  created_to?: string
  include_archived?: boolean
}

/**
 * 将筛选与分页参数转换为 GET 查询对象。
 * 将 `created_from` / `created_to` 映射为 FastAPI 当前实现使用的 `created_after` / `created_before`。
 */
export function caseListQueryFromFilters(
  filters: CaseListFilters,
  pagination: {
    limit?: number
    cursor_created_at?: string | null
    cursor_case_id?: string | null
  }
): Record<string, string | number | boolean | undefined> {
  const limit = pagination.limit ?? DEFAULT_LIMIT
  const q: Record<string, string | number | boolean | undefined> = { limit }

  const brand = filters.brand_id?.trim()
  const store = filters.store_id?.trim()
  if (brand) q.brand_id = brand
  if (store) q.store_id = store

  if (filters.problem_type) q.problem_type = filters.problem_type
  if (filters.status) q.status = filters.status

  if (filters.include_archived === true) q.include_archived = true

  const from = filters.created_from?.trim()
  const to = filters.created_to?.trim()
  if (from) q.created_after = from
  if (to) q.created_before = to

  const cAt = pagination.cursor_created_at
  const cId = pagination.cursor_case_id
  if (cAt && cId) {
    q.cursor_created_at = cAt
    q.cursor_case_id = cId
  }

  return q
}

export interface UseCaseListReturn {
  items: Ref<CaseListItem[]>
  listPhase: Ref<CaseListPhase>
  listError: Ref<ApiError | null>
  lastPageMeta: Ref<PaginatedCaseListResponse | null>
  hasNextPage: ComputedRef<boolean>
  isLoadingMore: Ref<boolean>
  loadMoreError: Ref<ApiError | null>
  currentFilters: Ref<CaseListFilters>
  loadInitial: (filters: CaseListFilters) => Promise<void>
  loadMore: () => Promise<void>
  retryInitial: () => Promise<void>
  retryLoadMore: () => Promise<void>
}

export function useCaseList(caseApi: CaseApiService): UseCaseListReturn {
  const items = ref<CaseListItem[]>([]) as Ref<CaseListItem[]>
  const listPhase = ref<CaseListPhase>('idle')
  const listError = ref<ApiError | null>(null)
  const lastPageMeta = ref<PaginatedCaseListResponse | null>(null)
  const currentFilters = ref<CaseListFilters>({})
  const isLoadingMore = ref(false)
  const loadMoreError = ref<ApiError | null>(null)

  const hasNextPage = computed(() => Boolean(lastPageMeta.value?.has_more))

  async function loadInitial(filters: CaseListFilters): Promise<void> {
    currentFilters.value = { ...filters }
    items.value = []
    lastPageMeta.value = null
    listError.value = null
    loadMoreError.value = null
    listPhase.value = 'loading'

    const q = caseListQueryFromFilters(currentFilters.value, { limit: DEFAULT_LIMIT })
    const res = await caseApi.list(q as CaseListQuery)

    if (!res.ok) {
      listError.value = res.error
      listPhase.value = 'error'
      return
    }

    lastPageMeta.value = res.data
    items.value = [...res.data.items]
    listPhase.value = res.data.items.length === 0 ? 'empty' : 'success'
  }

  async function loadMore(): Promise<void> {
    if (!hasNextPage.value || isLoadingMore.value) return
    const meta = lastPageMeta.value
    if (!meta?.next_cursor_created_at || !meta?.next_cursor_case_id) return

    isLoadingMore.value = true
    loadMoreError.value = null

    const q = caseListQueryFromFilters(currentFilters.value, {
      limit: meta.limit ?? DEFAULT_LIMIT,
      cursor_created_at: meta.next_cursor_created_at,
      cursor_case_id: meta.next_cursor_case_id,
    })

    const res = await caseApi.list(q as CaseListQuery)
    isLoadingMore.value = false

    if (!res.ok) {
      loadMoreError.value = res.error
      return
    }

    lastPageMeta.value = res.data
    items.value = [...items.value, ...res.data.items]
  }

  async function retryInitial(): Promise<void> {
    await loadInitial(currentFilters.value)
  }

  async function retryLoadMore(): Promise<void> {
    await loadMore()
  }

  return {
    items,
    listPhase,
    listError,
    lastPageMeta,
    hasNextPage,
    isLoadingMore,
    loadMoreError,
    currentFilters,
    loadInitial,
    loadMore,
    retryInitial,
    retryLoadMore,
  }
}
