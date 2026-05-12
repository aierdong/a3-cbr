/**
 * 推荐反馈 API service：消费 openapi-typescript 生成的契约类型；MVP 注入匿名 actor 与后台渠道。
 * 满足 requirements.md § 6.1、6.3；design.md § FeedbackApiService
 */

import type { ApiClient } from './client'
import type { ApiResult } from './errors'
import type { components } from './generated/feedback'

const FEEDBACK_PATH = '/api/recommendation-feedback'
const MVP_ANONYMOUS_ACTOR = 'anonymous_user'
const MVP_SOURCE_CHANNEL: components['schemas']['SourceChannel'] = 'admin_web'

export type FeedbackCreateRequest = components['schemas']['FeedbackCreateRequest']
export type FeedbackResponse = components['schemas']['FeedbackResponse']

/** 页面/控件侧输入：actor_id、source_channel 由 service 统一补全 */
export type FeedbackSubmitInput = Omit<FeedbackCreateRequest, 'actor_id' | 'source_channel'> &
  Partial<Pick<FeedbackCreateRequest, 'actor_id' | 'source_channel'>>

export function createFeedbackApiService(client: ApiClient) {
  return {
    submit(body: FeedbackSubmitInput): Promise<ApiResult<FeedbackResponse>> {
      const payload: FeedbackCreateRequest = {
        ...body,
        actor_id: body.actor_id ?? MVP_ANONYMOUS_ACTOR,
        source_channel: body.source_channel ?? MVP_SOURCE_CHANNEL,
      }
      return client.post<FeedbackCreateRequest, FeedbackResponse>(FEEDBACK_PATH, payload)
    },
  }
}

export type FeedbackApiService = ReturnType<typeof createFeedbackApiService>
