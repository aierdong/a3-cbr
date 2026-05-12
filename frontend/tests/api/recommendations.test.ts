import { describe, it, expect, vi } from 'vitest'
import { createRecommendationApiService } from '../../src/api/recommendations'
import type { ApiClient } from '../../src/api/client'

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
})
