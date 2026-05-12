/**
 * 推荐检索 API service：消费 openapi-typescript 生成的契约类型。
 * 满足 requirements.md § 4.1–4.5、6.1、6.3；design.md § RecommendationApiService
 *
 * 响应体中的 `items` 数组顺序与后端一致；本层不对推荐项做任何重排。
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components } from './generated/recommendations'

const SIMILAR_CASES_PATH = '/api/recommendations/similar-cases'

export type RecommendationRequest = components['schemas']['RecommendationRequest']
export type RecommendationResponse = components['schemas']['RecommendationResponse']
export type RecommendationFilters = components['schemas']['RecommendationFilters']
export type RecommendationItem = components['schemas']['RecommendationItem']
export type QueryMetadata = components['schemas']['QueryMetadata']
export type RecommendationStatus = components['schemas']['RecommendationStatus']
export type DegradedReason = components['schemas']['DegradedReason']
export type ExplanationStatus = components['schemas']['ExplanationStatus']
export type ScoreBreakdown = components['schemas']['ScoreBreakdown']
export type ScoreFinalSource = components['schemas']['ScoreFinalSource']
export type CaseReference = components['schemas']['CaseReference']
export type BusinessWeights = components['schemas']['BusinessWeights']
export type RecommendationFieldError = components['schemas']['ErrorField']

export function createRecommendationApiService(client: ApiClient) {
  return {
    /**
     * POST `/api/recommendations/similar-cases`
     * 成功时返回的 `data.items` 保持服务端顺序，调用方不得重排。
     */
    recommendSimilarCases(body: RecommendationRequest): Promise<ApiResult<RecommendationResponse>> {
      return client.post<RecommendationRequest, RecommendationResponse>(SIMILAR_CASES_PATH, body)
    },
  }
}

export type RecommendationApiService = ReturnType<typeof createRecommendationApiService>
