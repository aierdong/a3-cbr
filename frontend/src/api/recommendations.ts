/**
 * 推荐检索 API service：消费 openapi-typescript 生成的契约类型。
 * 满足 requirements.md § 6.1、6.3；design.md § RecommendationApiService
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components } from './generated/recommendations'

const SIMILAR_CASES_PATH = '/api/recommendations/similar-cases'

export type RecommendationRequest = components['schemas']['RecommendationRequest']
export type RecommendationResponse = components['schemas']['RecommendationResponse']

export function createRecommendationApiService(client: ApiClient) {
  return {
    recommendSimilarCases(body: RecommendationRequest): Promise<ApiResult<RecommendationResponse>> {
      return client.post<RecommendationRequest, RecommendationResponse>(SIMILAR_CASES_PATH, body)
    },
  }
}

export type RecommendationApiService = ReturnType<typeof createRecommendationApiService>
