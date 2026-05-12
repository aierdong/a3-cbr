/**
 * 案例 API service：消费 openapi-typescript 生成的契约类型。
 * 满足 requirements.md § 6.1、6.3；design.md § CaseApiService、Contract Synchronization
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components, operations } from './generated/cases'

const CASES_BASE = '/api/a3-cases'

/** 列表行：对齐 OpenAPI `CaseListItem`（requirements 2.1 / design 数据模型） */
export type CaseListItem = components['schemas']['CaseListItem']
/** 契约中的字段错误项；结构与 `ApiError.fields` 的 `FieldError` 一致（422） */
export type CaseFieldError = components['schemas']['ErrorField']

export type CreateCaseRequest = components['schemas']['CreateCaseRequest']
export type UpdateCaseRequest = components['schemas']['UpdateCaseRequest']
export type CaseDetailResponse = components['schemas']['CaseDetailResponse']
export type PaginatedCaseListResponse = components['schemas']['PaginatedCaseListResponse']
export type CaseListQuery = NonNullable<operations['listA3Cases']['parameters']['query']>

export function createCaseApiService(client: ApiClient) {
  return {
    list(query?: CaseListQuery): Promise<ApiResult<PaginatedCaseListResponse>> {
      return client.get<PaginatedCaseListResponse>(
        CASES_BASE,
        query as Record<string, string | number | boolean | undefined>
      )
    },

    create(body: CreateCaseRequest): Promise<ApiResult<CaseDetailResponse>> {
      return client.post<CreateCaseRequest, CaseDetailResponse>(CASES_BASE, body)
    },

    /** 案例详情：GET `/api/a3-cases/{case_id}` */
    detail(caseId: string): Promise<ApiResult<CaseDetailResponse>> {
      const path = `${CASES_BASE}/${encodeURIComponent(caseId)}`
      return client.get<CaseDetailResponse>(path)
    },

    update(caseId: string, body: UpdateCaseRequest): Promise<ApiResult<CaseDetailResponse>> {
      const path = `${CASES_BASE}/${encodeURIComponent(caseId)}`
      return client.put<UpdateCaseRequest, CaseDetailResponse>(path, body)
    },
  }
}

export type CaseApiService = ReturnType<typeof createCaseApiService>
