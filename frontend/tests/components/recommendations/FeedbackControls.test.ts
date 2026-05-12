import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import FeedbackControls from '../../../src/components/recommendations/FeedbackControls.vue'
import type { FeedbackApiService, FeedbackResponse } from '../../../src/api/feedback'

const runSuccess = (): FeedbackResponse => ({
  feedback_id: 'f1',
  recommendation_run_id: 'r1',
  recommendation_item_id: null,
  case_id: null,
  usefulness: 'useful',
  comment: null,
  target_scope: 'run',
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T01:00:00.000Z',
})

describe('FeedbackControls', () => {
  it('运行级提交成功时展示已保存与更新时间', async () => {
    const submit = vi.fn().mockResolvedValue({ ok: true, data: runSuccess() })
    const feedbackApi = { submit } as unknown as FeedbackApiService
    const w = mount(FeedbackControls, {
      props: { feedbackApi, recommendationRunId: 'r1' },
    })
    await w.find('[data-testid="feedback-submit"]').trigger('click')
    await flushPromises()
    expect(submit).toHaveBeenCalledWith({
      recommendation_run_id: 'r1',
      recommendation_item_id: null,
      usefulness: 'unknown',
      comment: null,
    })
    expect(w.find('[data-testid="feedback-success"]').exists()).toBe(true)
    expect(w.text()).toContain('已保存')
  })

  it('提交失败时展示错误提示', async () => {
    const submit = vi.fn().mockResolvedValue({
      ok: false,
      error: {
        kind: 'not_found',
        code: 'FEEDBACK_TARGET_NOT_FOUND',
        message: 'not found',
        status: 404,
      },
    })
    const feedbackApi = { submit } as unknown as FeedbackApiService
    const w = mount(FeedbackControls, {
      props: { feedbackApi, recommendationRunId: 'r1' },
    })
    await w.find('[data-testid="feedback-submit"]').trigger('click')
    await flushPromises()
    expect(w.find('.fb-error').exists()).toBe(true)
    expect(w.text()).toContain('不存在')
  })

  it('推荐项级提交应携带 recommendation_item_id', async () => {
    const submit = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        ...runSuccess(),
        recommendation_item_id: 'it99',
        target_scope: 'item',
      },
    })
    const feedbackApi = { submit } as unknown as FeedbackApiService
    const w = mount(FeedbackControls, {
      props: { feedbackApi, recommendationRunId: 'r1', recommendationItemId: 'it99' },
    })
    await w.find('[data-testid="feedback-submit"]').trigger('click')
    await flushPromises()
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        recommendation_run_id: 'r1',
        recommendation_item_id: 'it99',
      })
    )
  })
})
