/**
 * 案例增强触发 API：消费 `llm-case-enrichment` OpenAPI 生成类型。
 * 与 `mvp-admin-frontend` design 中 EnrichmentApiService 对齐。
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components } from './generated/enrichment'

const CASES_ENRICHMENT_BASE = '/api/a3-cases'

export type CreateEnrichmentRunRequest = components['schemas']['CreateEnrichmentRunRequest']
export type EnrichmentRunResponse = components['schemas']['EnrichmentRunResponse']
export type CaseEnrichmentStatusResponse = components['schemas']['CaseEnrichmentStatusResponse']

export function createEnrichmentApiService(client: ApiClient) {
  return {
    getCaseEnrichmentStatus(caseId: string): Promise<ApiResult<CaseEnrichmentStatusResponse>> {
      const path = `${CASES_ENRICHMENT_BASE}/${encodeURIComponent(caseId)}/enrichment`
      return client.get<CaseEnrichmentStatusResponse>(path)
    },

    createEnrichmentRun(
      caseId: string,
      body: CreateEnrichmentRunRequest = {}
    ): Promise<ApiResult<EnrichmentRunResponse>> {
      const path = `${CASES_ENRICHMENT_BASE}/${encodeURIComponent(caseId)}/enrichment-runs`
      return client.post<CreateEnrichmentRunRequest, EnrichmentRunResponse>(path, body)
    },
  }
}

export type EnrichmentApiService = ReturnType<typeof createEnrichmentApiService>
