import { describe, it, expect, vi } from 'vitest'
import { createFeedbackApiService } from '../../src/api/feedback'
import type { ApiClient } from '../../src/api/client'

describe('createFeedbackApiService', () => {
  it('submit 应注入 actor_id 与 source_channel 并 POST /api/recommendation-feedback', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createFeedbackApiService(client)
    await api.submit({
      recommendation_run_id: 'run-1',
      usefulness: 'useful',
    })
    expect(post).toHaveBeenCalledWith('/api/recommendation-feedback', {
      recommendation_run_id: 'run-1',
      usefulness: 'useful',
      actor_id: 'anonymous_user',
      source_channel: 'admin_web',
    })
  })

  it('submit 在显式传入 actor_id 时应保留调用方值', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createFeedbackApiService(client)
    await api.submit({
      recommendation_run_id: 'run-1',
      usefulness: 'unknown',
      actor_id: 'u-99',
    })
    expect(post).toHaveBeenCalledWith(
      '/api/recommendation-feedback',
      expect.objectContaining({ actor_id: 'u-99', source_channel: 'admin_web' })
    )
  })
})
