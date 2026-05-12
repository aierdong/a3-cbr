import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RecommendationSearchForm from '../../../src/components/recommendations/RecommendationSearchForm.vue'
import {
  defaultRecommendationSearchDraft,
  type RecommendationSearchDraft,
} from '../../../src/composables/useRecommendations'

describe('RecommendationSearchForm', () => {
  it('提交时应发出 update:modelValue 与 submit', async () => {
    const draft: RecommendationSearchDraft = {
      ...defaultRecommendationSearchDraft(),
      query_text: '门店客诉',
      top_k: 8,
    }
    const w = mount(RecommendationSearchForm, {
      props: {
        modelValue: draft,
        fieldErrors: {},
        submitting: false,
      },
    })
    await w.find('textarea').setValue('新的问题')
    await w.find('form').trigger('submit')
    const updates = w.emitted('update:modelValue') ?? []
    expect(updates.length).toBeGreaterThanOrEqual(1)
    const last = updates[updates.length - 1]![0] as RecommendationSearchDraft
    expect(last.query_text).toBe('新的问题')
    expect(w.emitted('submit')).toBeTruthy()
  })

  it('应展示 query_text 字段错误', () => {
    const w = mount(RecommendationSearchForm, {
      props: {
        modelValue: defaultRecommendationSearchDraft(),
        fieldErrors: { query_text: '请输入当前问题描述' },
        submitting: false,
      },
    })
    expect(w.get('[data-testid="err-query_text"]').text()).toContain('请输入')
  })
})
