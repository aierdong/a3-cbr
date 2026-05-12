import { describe, it, expect, vi } from 'vitest'
import { createRecommendationApiService } from '../../src/api/recommendations'
import type { ApiClient } from '../../src/api/client'
import type { RecommendationResponse } from '../../src/api/recommendations'

describe('createRecommendationApiService', () => {
  it('recommendSimilarCases 应对 /api/recommendations/similar-cases 发起 POST', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createRecommendationApiService(client)
    const body = {
      query_text: '当前问题',
      top_k: 5,
    }
    await api.recommendSimilarCases(body)
    expect(post).toHaveBeenCalledWith('/api/recommendations/similar-cases', body)
  })

  it('应原样传递含 filters 的请求体', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createRecommendationApiService(client)
    const body = {
      query_text: '问题',
      top_k: 3,
      filters: {
        brand_id: 'b1',
        tags: ['x', 'y'],
        case_status: 'active',
      },
    }
    await api.recommendSimilarCases(body)
    expect(post).toHaveBeenCalledWith('/api/recommendations/similar-cases', body)
  })

  it('成功响应应保持 items 数组顺序（不在 service 层重排）', async () => {
    const ordered: RecommendationResponse['items'] = [
      makeItem('1', 'c-a', 1),
      makeItem('2', 'c-b', 2),
      makeItem('3', 'c-c', 3),
    ]
    const data: RecommendationResponse = {
      recommendation_run_id: 'run-1',
      contract_version: 'v1',
      status: 'succeeded',
      applied_filters: {},
      score_weights: {},
      query_metadata: {
        query_hash: 'h',
        requested_top_k: 3,
        vector_candidate_count: 10,
        returned_count: 3,
        latency_ms: 12,
      },
      items: ordered,
    }
    const post = vi.fn().mockResolvedValue({ ok: true, data })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createRecommendationApiService(client)
    const res = await api.recommendSimilarCases({ query_text: 'q', top_k: 3 })
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.data.items.map((i) => i.case_id)).toEqual(['c-a', 'c-b', 'c-c'])
    }
  })
})

function makeItem(
  rid: string,
  caseId: string,
  rank: number
): RecommendationResponse['items'][number] {
  return {
    recommendation_item_id: rid,
    case_id: caseId,
    rank,
    case_reference: {
      title_preview: 't',
      description_preview: 'd',
      case_updated_at: '2026-01-01T00:00:00Z',
    },
    vector_similarity_score: 0.5,
    final_score: 0.5,
    score_breakdown: { final_score_source: 'aggregated' },
    explanation_status: 'generated',
    missing_fields: [],
  }
}
