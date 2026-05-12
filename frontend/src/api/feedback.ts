/**
 * 推荐反馈 API service：消费 openapi-typescript 生成的契约类型；MVP 注入匿名 actor 与后台渠道。
 * 满足 requirements.md § 5.1–5.4、6.1、6.3；design.md § FeedbackApiService、反馈错误映射
 */

import type { ApiClient } from './client'
import type { ApiError, ApiResult } from './errors'
import { apiFieldErrorsToMap } from './errors'
import type { components } from './generated/feedback'

const FEEDBACK_PATH = '/api/recommendation-feedback'
const MVP_ANONYMOUS_ACTOR = 'anonymous_user'
const MVP_SOURCE_CHANNEL: components['schemas']['SourceChannel'] = 'admin_web'

export type FeedbackCreateRequest = components['schemas']['FeedbackCreateRequest']
export type FeedbackResponse = components['schemas']['FeedbackResponse']
export type Usefulness = components['schemas']['Usefulness']
export type SourceChannel = components['schemas']['SourceChannel']
export type TargetScope = components['schemas']['TargetScope']

/**
 * 与后端「按目标 upsert」幂等行为对齐的复合键（契约无独立 idempotency header/字段）。
 * 同一 `recommendation_run_id` + `recommendation_item_id`（null 表示运行级）+ 提交者下重复提交覆盖。
 */
export type FeedbackUpsertTargetKey = Pick<
  FeedbackCreateRequest,
  'recommendation_run_id' | 'recommendation_item_id'
>

/** 页面/控件侧输入：actor_id、source_channel 由 service 统一补全 */
export type FeedbackSubmitInput = Omit<FeedbackCreateRequest, 'actor_id' | 'source_channel'> &
  Partial<Pick<FeedbackCreateRequest, 'actor_id' | 'source_channel'>>

/** 反馈控件局部错误展示（不清空推荐结果，design.md § 5.4） */
export interface FeedbackControlErrorState {
  message: string
  fieldMessages: Record<string, string>
  showRetry: boolean
}

export function feedbackControlStateFromApiError(error: ApiError): FeedbackControlErrorState {
  const fieldMessages =
    error.kind === 'validation' && error.fields?.length ? apiFieldErrorsToMap(error.fields) : {}

  const showRetry =
    error.kind === 'system' ||
    error.kind === 'network' ||
    error.kind === 'dependency_unavailable'

  let message = error.message
  switch (error.code) {
    case 'FEEDBACK_TARGET_NOT_FOUND':
      message = '推荐运行或推荐项不存在，反馈未保存。'
      break
    case 'FEEDBACK_TARGET_MISMATCH':
      message = '推荐项不属于当前推荐运行，反馈未保存。'
      break
    case 'VALIDATION_ERROR':
      if (!error.fields?.length) {
        message = '反馈内容无效，请检查输入。'
      }
      break
    default:
      break
  }

  return { message, fieldMessages, showRetry }
}

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
