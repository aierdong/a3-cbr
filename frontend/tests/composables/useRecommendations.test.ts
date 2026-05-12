import { describe, it, expect, vi } from 'vitest'
import {
  buildRecommendationRequest,
  defaultRecommendationSearchDraft,
  useRecommendations,
} from '../../src/composables/useRecommendations'
import type { RecommendationApiService } from '../../src/api/recommendations'

describe('buildRecommendationRequest', () => {
  it('应省略全部为空的 filters', () => {
    const d = defaultRecommendationSearchDraft()
    d.query_text = '问题描述'
    const b = buildRecommendationRequest(d)
    expect(b.filters).toBeUndefined()
    expect(b.query_text).toBe('问题描述')
    expect(b.top_k).toBe(20)
  })

  it('应映射非空过滤字段并拆分 tags', () => {
    const d = defaultRecommendationSearchDraft()
    d.query_text = 'q'
    d.top_k = 5
    d.brand_id = 'br'
    d.tags = 'a, b，c'
    d.case_status = 'draft'
    const b = buildRecommendationRequest(d)
    expect(b.filters?.brand_id).toBe('br')
    expect(b.filters?.tags).toEqual(['a', 'b', 'c'])
    expect(b.filters?.case_status).toBe('draft')
  })

  it('应将 top_k 限制在 1–100', () => {
    const d = defaultRecommendationSearchDraft()
    d.query_text = 'x'
    d.top_k = 0
    expect(buildRecommendationRequest(d).top_k).toBe(1)
    d.top_k = 500
    expect(buildRecommendationRequest(d).top_k).toBe(100)
  })
})

describe('useRecommendations', () => {
  it('空问题时不调用 API 并返回字段提示', async () => {
    const recommendSimilarCases = vi.fn()
    const api = { recommendSimilarCases } as unknown as RecommendationApiService
    const { draft, search, fieldErrors } = useRecommendations(api)
    draft.value.query_text = '   '
    await search()
    expect(recommendSimilarCases).not.toHaveBeenCalled()
    expect(fieldErrors.value.query_text).toBeTruthy()
  })

  it('422 时映射字段错误', async () => {
    const recommendSimilarCases = vi.fn().mockResolvedValue({
      ok: false,
      error: {
        kind: 'validation' as const,
        code: 'VALIDATION_ERROR',
        message: '参数无效',
        status: 422,
        fields: [{ field: 'query_text', message: '不能为空' }],
      },
    })
    const api = { recommendSimilarCases } as unknown as RecommendationApiService
    const { draft, search, fieldErrors, lastResult } = useRecommendations(api)
    draft.value.query_text = 'x'
    await search()
    expect(fieldErrors.value.query_text).toBe('不能为空')
    expect(lastResult.value).toBeNull()
  })

  it('检索失败后应保留上一次成功结果以便继续查看与反馈（需求 4.4、5.4）', async () => {
    const payload = {
      recommendation_run_id: 'r-keep',
      contract_version: 'v1',
      status: 'succeeded' as const,
      applied_filters: {},
      score_weights: {},
      query_metadata: {
        query_hash: 'h',
        requested_top_k: 2,
        vector_candidate_count: 1,
        returned_count: 1,
        latency_ms: 1,
      },
      items: [
        {
          recommendation_item_id: 'i1',
          case_id: 'c1',
          rank: 1,
          case_reference: {
            title_preview: 't',
            description_preview: 'd',
            case_updated_at: '2026-01-01T00:00:00Z',
          },
          vector_similarity_score: 0.1,
          final_score: 0.2,
          score_breakdown: { final_score_source: 'aggregated' as const },
          explanation_status: 'generated' as const,
          missing_fields: [],
        },
      ],
    }
    const recommendSimilarCases = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, data: payload })
      .mockResolvedValueOnce({
        ok: false,
        error: {
          kind: 'system' as const,
          code: 'INTERNAL_ERROR',
          message: '系统异常',
          status: 500,
        },
      })
    const api = { recommendSimilarCases } as unknown as RecommendationApiService
    const { draft, search, lastResult, pageError } = useRecommendations(api)
    draft.value.query_text = '第一次'
    await search()
    expect(lastResult.value?.recommendation_run_id).toBe('r-keep')
    draft.value.query_text = '第二次'
    await search()
    expect(lastResult.value?.recommendation_run_id).toBe('r-keep')
    expect(pageError.value?.kind).toBe('system')
  })

  it('成功时写入 lastResult', async () => {
    const payload = {
      recommendation_run_id: 'r1',
      contract_version: 'v1',
      status: 'succeeded' as const,
      applied_filters: { brand_id: 'b' },
      score_weights: { brand: 0.2 },
      query_metadata: {
        query_hash: 'h',
        requested_top_k: 2,
        vector_candidate_count: 5,
        returned_count: 1,
        latency_ms: 1,
      },
      items: [
        {
          recommendation_item_id: 'i1',
          case_id: 'c1',
          rank: 1,
          case_reference: {
            title_preview: 't',
            description_preview: 'd',
            case_updated_at: '2026-01-01T00:00:00Z',
          },
          vector_similarity_score: 0.1,
          final_score: 0.2,
          score_breakdown: { final_score_source: 'aggregated' as const },
          explanation_status: 'generated' as const,
          missing_fields: [],
        },
      ],
    }
    const recommendSimilarCases = vi.fn().mockResolvedValue({ ok: true, data: payload })
    const api = { recommendSimilarCases } as unknown as RecommendationApiService
    const { draft, search, lastResult } = useRecommendations(api)
    draft.value.query_text = '问题'
    await search()
    expect(lastResult.value?.recommendation_run_id).toBe('r1')
    expect(lastResult.value?.items[0]?.case_id).toBe('c1')
  })
})
