import { describe, it, expect, vi } from 'vitest'
import { createEnrichmentApiService } from '../../src/api/enrichment'
import type { ApiClient } from '../../src/api/client'

function mockClient(partial: Partial<ApiClient>): ApiClient {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    ...partial,
  }
}

describe('createEnrichmentApiService', () => {
  it('getCaseEnrichmentStatus 应对 /api/a3-cases/{case_id}/enrichment 发起 GET', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: { case_id: 'c1', latest_run: null, current_result: null } })
    const api = createEnrichmentApiService(mockClient({ get }))
    await api.getCaseEnrichmentStatus('case-abc')
    expect(get).toHaveBeenCalledWith('/api/a3-cases/case-abc/enrichment')
  })

  it('createEnrichmentRun 应对 /api/a3-cases/{case_id}/enrichment-runs 发起 POST', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: { run_id: 'r1' } })
    const api = createEnrichmentApiService(mockClient({ post }))
    await api.createEnrichmentRun('case-abc', {})
    expect(post).toHaveBeenCalledWith('/api/a3-cases/case-abc/enrichment-runs', {})
  })

  it('createEnrichmentRun 应对 case_id 做路径编码', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createEnrichmentApiService(mockClient({ post }))
    await api.createEnrichmentRun('a/b', {})
    expect(post).toHaveBeenCalledWith('/api/a3-cases/a%2Fb/enrichment-runs', {})
  })
})
