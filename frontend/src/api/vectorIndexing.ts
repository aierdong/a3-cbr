/**
 * 案例向量索引 API：消费 case-vector-indexing OpenAPI 生成类型。
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components } from './generated/vectorIndexing'

const CASES_BASE = '/api/a3-cases'
const VECTOR_INDEX_BASE = '/api/vector-index'

export type RefreshVectorIndexRequest = components['schemas']['RefreshVectorIndexRequest']
export type VectorIndexJobResponse = components['schemas']['VectorIndexJobResponse']
export type VectorIndexStatusResponse = components['schemas']['VectorIndexStatusResponse']

export function createVectorIndexingApiService(client: ApiClient) {
  return {
    getCaseVectorIndexStatus(caseId: string): Promise<ApiResult<VectorIndexStatusResponse>> {
      const path = `${CASES_BASE}/${encodeURIComponent(caseId)}/vector-index`
      return client.get<VectorIndexStatusResponse>(path)
    },

    refreshCaseVectorIndex(
      caseId: string,
      body: RefreshVectorIndexRequest
    ): Promise<ApiResult<VectorIndexJobResponse>> {
      const path = `${CASES_BASE}/${encodeURIComponent(caseId)}/vector-index/refresh`
      return client.post<RefreshVectorIndexRequest, VectorIndexJobResponse>(path, body)
    },

    retryVectorIndexJob(jobId: string): Promise<ApiResult<VectorIndexJobResponse>> {
      const path = `${VECTOR_INDEX_BASE}/jobs/${encodeURIComponent(jobId)}/retry`
      return client.post<Record<string, never>, VectorIndexJobResponse>(path, {})
    },
  }
}

export type VectorIndexingApiService = ReturnType<typeof createVectorIndexingApiService>
