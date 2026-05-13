/**
 * 详情页「增强 / 向量化」成功与否的展示规则（对齐 docs/contract-a3-case-detail-for-enrichment.md §6.5）
 */

import type { CaseEnrichmentStatusResponse } from '@/api/enrichment'
import type { VectorIndexStatusResponse } from '@/api/vectorIndexing'

export type EnrichmentRunStatus = NonNullable<
  CaseEnrichmentStatusResponse['latest_run']
>['status']
export type CaseEnrichmentResultStatus = NonNullable<
  CaseEnrichmentStatusResponse['current_result']
>['status']
export type VectorCaseStatus = VectorIndexStatusResponse['status']
export type VectorJobStatus = NonNullable<VectorIndexStatusResponse['latest_job']>['status']

export function isEnrichmentDetailOk(s: CaseEnrichmentStatusResponse): boolean {
  const run = s.latest_run
  const res = s.current_result
  return run?.status === 'succeeded' && res?.status === 'valid'
}

export function isVectorDetailOk(s: VectorIndexStatusResponse): boolean {
  return s.status === 'published' || s.status === 'succeeded'
}

export function formatEnrichmentSummary(s: CaseEnrichmentStatusResponse): string {
  const run = s.latest_run
  const res = s.current_result
  if (!run && !res) return '尚无增强记录'
  if (run?.status === 'succeeded' && res?.status === 'valid') return '已成功并存在有效派生结果'
  const parts: string[] = []
  if (run?.status) parts.push(`最近运行：${run.status}`)
  if (res?.status) parts.push(`派生状态：${res.status}`)
  return parts.length ? parts.join(' · ') : '状态未知'
}

export function formatVectorSummary(s: VectorIndexStatusResponse): string {
  const st = s.status
  const job = s.latest_job
  const extra = s.message || s.last_error_code
  const base = `聚合状态：${st}`
  if (job?.status) return extra ? `${base} · 最近任务：${job.status} · ${extra}` : `${base} · 最近任务：${job.status}`
  return extra ? `${base} · ${extra}` : base
}
