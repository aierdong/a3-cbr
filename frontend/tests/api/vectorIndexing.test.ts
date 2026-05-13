import { describe, it, expect, vi } from 'vitest'
import { createVectorIndexingApiService } from '../../src/api/vectorIndexing'
import type { ApiClient } from '../../src/api/client'

function mockClient(partial: Partial<ApiClient>): ApiClient {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    ...partial,
  }
}

describe('createVectorIndexingApiService', () => {
  it('getCaseVectorIndexStatus 应对 /api/a3-cases/{case_id}/vector-index 发起 GET', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: { case_id: 'c1', status: 'published' } })
    const api = createVectorIndexingApiService(mockClient({ get }))
    await api.getCaseVectorIndexStatus('case-abc')
    expect(get).toHaveBeenCalledWith('/api/a3-cases/case-abc/vector-index')
  })

  it('refreshCaseVectorIndex 应对 refresh 发起 POST', async () => {
    const body = { force_rebuild: false, carry_retry_count: 0, requested_by: 't' }
    const post = vi.fn().mockResolvedValue({ ok: true, data: { status: 'succeeded' } })
    const api = createVectorIndexingApiService(mockClient({ post }))
    await api.refreshCaseVectorIndex('case-abc', body)
    expect(post).toHaveBeenCalledWith('/api/a3-cases/case-abc/vector-index/refresh', body)
  })

  it('retryVectorIndexJob 应对 /api/vector-index/jobs/{job_id}/retry 发起 POST', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createVectorIndexingApiService(mockClient({ post }))
    await api.retryVectorIndexJob('job-99')
    expect(post).toHaveBeenCalledWith('/api/vector-index/jobs/job-99/retry', {})
  })
})
