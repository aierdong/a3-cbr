import { describe, it, expect, vi } from 'vitest'
import {
  feedbackControlStateFromApiError,
  createFeedbackApiService,
} from '../../src/api/feedback'
import type { ApiError } from '../../src/api/errors'
import type { ApiClient } from '../../src/api/client'

describe('createFeedbackApiService', () => {
  it('submit 应注入 actor_id 与 source_channel 并 POST /api/recommendation-feedback', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createFeedbackApiService(client)
    await api.submit({
      recommendation_run_id: 'run-1',
      usefulness: 'useful',
    })
    expect(post).toHaveBeenCalledWith('/api/recommendation-feedback', {
      recommendation_run_id: 'run-1',
      usefulness: 'useful',
      actor_id: 'anonymous_user',
      source_channel: 'admin_web',
    })
  })

  it('submit 在显式传入 actor_id 时应保留调用方值', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createFeedbackApiService(client)
    await api.submit({
      recommendation_run_id: 'run-1',
      usefulness: 'unknown',
      actor_id: 'u-99',
    })
    expect(post).toHaveBeenCalledWith(
      '/api/recommendation-feedback',
      expect.objectContaining({ actor_id: 'u-99', source_channel: 'admin_web' })
    )
  })

  it('submit 推荐项级应包含 recommendation_item_id 与 comment', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const client: ApiClient = { get: vi.fn(), post, put: vi.fn() }
    const api = createFeedbackApiService(client)
    await api.submit({
      recommendation_run_id: 'run-1',
      recommendation_item_id: 'item-9',
      usefulness: 'not_useful',
      comment: '备注一行',
    })
    expect(post).toHaveBeenCalledWith('/api/recommendation-feedback', {
      recommendation_run_id: 'run-1',
      recommendation_item_id: 'item-9',
      usefulness: 'not_useful',
      comment: '备注一行',
      actor_id: 'anonymous_user',
      source_channel: 'admin_web',
    })
  })
})

describe('feedbackControlStateFromApiError', () => {
  it('422 应映射字段错误且默认不重试', () => {
    const error: ApiError = {
      kind: 'validation',
      code: 'VALIDATION_ERROR',
      message: '校验失败',
      status: 422,
      fields: [{ field: 'comment', message: '备注过长' }],
    }
    const s = feedbackControlStateFromApiError(error)
    expect(s.fieldMessages.comment).toBe('备注过长')
    expect(s.showRetry).toBe(false)
  })

  it('VALIDATION_ERROR 且无 fields 时应给出固定提示', () => {
    const error: ApiError = {
      kind: 'validation',
      code: 'VALIDATION_ERROR',
      message: 'x',
      status: 422,
    }
    expect(feedbackControlStateFromApiError(error).message).toBe('反馈内容无效，请检查输入。')
  })

  it('FEEDBACK_TARGET_NOT_FOUND 应稳定提示', () => {
    const error: ApiError = {
      kind: 'not_found',
      code: 'FEEDBACK_TARGET_NOT_FOUND',
      message: 'not found',
      status: 404,
    }
    expect(feedbackControlStateFromApiError(error).message).toContain('不存在')
    expect(feedbackControlStateFromApiError(error).showRetry).toBe(false)
  })

  it('FEEDBACK_TARGET_MISMATCH 应稳定提示', () => {
    const error: ApiError = {
      kind: 'conflict',
      code: 'FEEDBACK_TARGET_MISMATCH',
      message: 'conflict',
      status: 409,
    }
    expect(feedbackControlStateFromApiError(error).message).toContain('不属于')
  })

  it('系统错误应允许重试', () => {
    const error: ApiError = {
      kind: 'system',
      code: 'INTERNAL_ERROR',
      message: '内部错误',
      status: 500,
    }
    expect(feedbackControlStateFromApiError(error).showRetry).toBe(true)
  })

  it('控件错误状态仅含 message / fieldMessages / showRetry（需求 6.4）', () => {
    const error: ApiError = {
      kind: 'system',
      code: 'INTERNAL_ERROR',
      message: '系统异常',
      status: 500,
    }
    const s = feedbackControlStateFromApiError(error)
    expect(Object.keys(s).sort()).toEqual(['fieldMessages', 'message', 'showRetry'])
  })

  it('网络错误应允许重试', () => {
    const error: ApiError = {
      kind: 'network',
      code: 'NETWORK_ERROR',
      message: 'fail',
      status: 0,
    }
    expect(feedbackControlStateFromApiError(error).showRetry).toBe(true)
  })
})
