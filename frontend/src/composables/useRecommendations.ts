/**
 * 相似案例检索 composable（design.md § useRecommendations；tasks 3.2–3.3）
 */

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type {
  RecommendationApiService,
  RecommendationFilters,
  RecommendationRequest,
  RecommendationResponse,
} from '../api/recommendations'
import { apiFieldErrorsToMap, type ApiError } from '../api/errors'

const DEFAULT_TOP_K = 20

/** 表单草稿：仅包含契约中允许的过滤字段与检索参数 */
export interface RecommendationSearchDraft {
  query_text: string
  top_k: number
  brand_id: string
  store_id: string
  business_type: string
  store_scale: string
  franchise_type: string
  city: string
  city_tier: string
  problem_type: string
  /** 逗号分隔，提交时拆为 `filters.tags` */
  tags: string
  case_status: string
  created_at_from_local: string
  created_at_to_local: string
}

export function defaultRecommendationSearchDraft(): RecommendationSearchDraft {
  return {
    query_text: '',
    top_k: DEFAULT_TOP_K,
    brand_id: '',
    store_id: '',
    business_type: '',
    store_scale: '',
    franchise_type: '',
    city: '',
    city_tier: '',
    problem_type: '',
    tags: '',
    case_status: '',
    created_at_from_local: '',
    created_at_to_local: '',
  }
}

function localDatetimeToIso(local: string): string | undefined {
  if (!local.trim()) return undefined
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return undefined
  return d.toISOString()
}

function parseTags(raw: string): string[] | undefined {
  const parts = raw
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
  return parts.length ? parts : undefined
}

function clampTopK(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT_TOP_K
  const x = Math.trunc(n)
  if (x < 1) return 1
  if (x > 100) return 100
  return x
}

/**
 * 将表单草稿转换为 OpenAPI `RecommendationRequest`（不发送空字符串字段）。
 */
export function buildRecommendationRequest(draft: RecommendationSearchDraft): RecommendationRequest {
  const filters: RecommendationFilters = {}

  const brand_id = draft.brand_id.trim()
  const store_id = draft.store_id.trim()
  const business_type = draft.business_type.trim()
  const store_scale = draft.store_scale.trim()
  const franchise_type = draft.franchise_type.trim()
  const city = draft.city.trim()
  const city_tier = draft.city_tier.trim()
  const problem_type = draft.problem_type.trim()
  const case_status = draft.case_status.trim()

  if (brand_id) filters.brand_id = brand_id
  if (store_id) filters.store_id = store_id
  if (business_type) filters.business_type = business_type
  if (store_scale) filters.store_scale = store_scale
  if (franchise_type) filters.franchise_type = franchise_type
  if (city) filters.city = city
  if (city_tier) filters.city_tier = city_tier
  if (problem_type) filters.problem_type = problem_type
  if (case_status) filters.case_status = case_status

  const tags = parseTags(draft.tags)
  if (tags) filters.tags = tags

  const created_at_from = localDatetimeToIso(draft.created_at_from_local)
  const created_at_to = localDatetimeToIso(draft.created_at_to_local)
  if (created_at_from) filters.created_at_from = created_at_from
  if (created_at_to) filters.created_at_to = created_at_to

  const body: RecommendationRequest = {
    query_text: draft.query_text.trim(),
    top_k: clampTopK(draft.top_k),
  }
  if (Object.keys(filters).length > 0) {
    body.filters = filters
  }
  return body
}

export interface UseRecommendationsReturn {
  draft: Ref<RecommendationSearchDraft>
  lastResult: Ref<RecommendationResponse | null>
  submitting: Ref<boolean>
  pageError: Ref<ApiError | null>
  fieldErrors: ComputedRef<Record<string, string>>
  search: () => Promise<void>
  reset: () => void
}

export function useRecommendations(api: RecommendationApiService): UseRecommendationsReturn {
  const draft = ref<RecommendationSearchDraft>(defaultRecommendationSearchDraft())
  const lastResult = ref<RecommendationResponse | null>(null)
  const submitting = ref(false)
  const pageError = ref<ApiError | null>(null)
  const serverFieldMap = ref<Record<string, string>>({})

  const fieldErrors = computed(() => ({ ...serverFieldMap.value }))

  function reset(): void {
    draft.value = defaultRecommendationSearchDraft()
    lastResult.value = null
    pageError.value = null
    serverFieldMap.value = {}
    submitting.value = false
  }

  async function search(): Promise<void> {
    pageError.value = null
    serverFieldMap.value = {}

    const q = draft.value.query_text.trim()
    if (!q) {
      serverFieldMap.value = { query_text: '请输入当前问题描述' }
      return
    }

    submitting.value = true
    try {
      const body = buildRecommendationRequest({ ...draft.value, query_text: q })
      const res = await api.recommendSimilarCases(body)
      if (!res.ok) {
        pageError.value = res.error
        if (res.error.fields?.length) {
          serverFieldMap.value = apiFieldErrorsToMap(res.error.fields)
        }
        return
      }
      lastResult.value = res.data
    } finally {
      submitting.value = false
    }
  }

  return {
    draft,
    lastResult,
    submitting,
    pageError,
    fieldErrors,
    search,
    reset,
  }
}
