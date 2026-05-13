/**
 * 「提交且摘要」保存成功后的增强 → 向量串联（契约见 docs/contract-a3-case-detail-for-enrichment.md §6.1）
 */

import type { EnrichmentApiService } from '@/api/enrichment'
import type { VectorIndexingApiService } from '@/api/vectorIndexing'

export type SubmitPipelineFailureStage = 'enrichment' | 'vector'

export type SubmitPipelineResult =
  | { ok: true }
  | { ok: false; stage: SubmitPipelineFailureStage; message: string }

export async function runEnrichmentThenVectorRefresh(params: {
  caseId: string
  enrichmentApi: EnrichmentApiService
  vectorApi: VectorIndexingApiService
  requestedBy?: string
  /** 增强已成功、即将请求向量刷新时调用（可用于更新 UI loading 文案） */
  onBeforeVectorRefresh?: () => void
}): Promise<SubmitPipelineResult> {
  const { caseId, enrichmentApi, vectorApi, requestedBy = 'submit-with-summary', onBeforeVectorRefresh } = params
  const er = await enrichmentApi.createEnrichmentRun(caseId, {})
  if (!er.ok) {
    return { ok: false, stage: 'enrichment', message: er.error.message }
  }
  if (er.data.status !== 'succeeded') {
    return {
      ok: false,
      stage: 'enrichment',
      message: `增强未成功（状态：${er.data.status}），已跳过向量化`,
    }
  }
  onBeforeVectorRefresh?.()
  const vr = await vectorApi.refreshCaseVectorIndex(caseId, {
    force_rebuild: false,
    carry_retry_count: 0,
    requested_by: requestedBy,
  })
  if (!vr.ok) {
    return { ok: false, stage: 'vector', message: vr.error.message }
  }
  if (vr.data.status !== 'succeeded') {
    return {
      ok: false,
      stage: 'vector',
      message: `向量化未成功（作业状态：${vr.data.status}）`,
    }
  }
  return { ok: true }
}
