import { describe, it, expect, vi } from 'vitest'
import { runEnrichmentThenVectorRefresh } from '../../src/domain/submitWithSummaryPipeline'

function mkEnrichment(ok: boolean, status?: string) {
  return {
    createEnrichmentRun: vi.fn().mockResolvedValue(
      ok
        ? { ok: true, data: { status: status ?? 'succeeded' } }
        : { ok: false, error: { message: 'boom', kind: 'system', code: 'X', status: 500 } }
    ),
    getCaseEnrichmentStatus: vi.fn(),
  }
}

function mkVector(ok: boolean, jobStatus?: string) {
  return {
    refreshCaseVectorIndex: vi.fn().mockResolvedValue(
      ok
        ? { ok: true, data: { status: jobStatus ?? 'succeeded' } }
        : { ok: false, error: { message: 'vfail', kind: 'system', code: 'V', status: 500 } }
    ),
    getCaseVectorIndexStatus: vi.fn(),
    retryVectorIndexJob: vi.fn(),
  }
}

describe('runEnrichmentThenVectorRefresh', () => {
  it('增强 HTTP 失败则不走向量', async () => {
    const r = await runEnrichmentThenVectorRefresh({
      caseId: 'c1',
      enrichmentApi: mkEnrichment(false) as never,
      vectorApi: mkVector(true) as never,
    })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.stage).toBe('enrichment')
  })

  it('增强未 succeeded 则不调向量刷新', async () => {
    const vectorApi = mkVector(true) as never
    const enrichmentApi = mkEnrichment(true, 'failed') as never
    const r = await runEnrichmentThenVectorRefresh({
      caseId: 'c1',
      enrichmentApi,
      vectorApi,
    })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.stage).toBe('enrichment')
    expect(vectorApi.refreshCaseVectorIndex).not.toHaveBeenCalled()
  })

  it('增强成功后会调用向量刷新', async () => {
    const vectorApi = mkVector(true) as never
    const enrichmentApi = mkEnrichment(true, 'succeeded') as never
    const r = await runEnrichmentThenVectorRefresh({
      caseId: 'c1',
      enrichmentApi,
      vectorApi,
    })
    expect(r.ok).toBe(true)
    expect(vectorApi.refreshCaseVectorIndex).toHaveBeenCalledWith('c1', {
      force_rebuild: false,
      carry_retry_count: 0,
      requested_by: 'submit-with-summary',
    })
  })

  it('向量作业非 succeeded 返回失败', async () => {
    const r = await runEnrichmentThenVectorRefresh({
      caseId: 'c1',
      enrichmentApi: mkEnrichment(true, 'succeeded') as never,
      vectorApi: mkVector(true, 'failed') as never,
    })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.stage).toBe('vector')
  })
})
