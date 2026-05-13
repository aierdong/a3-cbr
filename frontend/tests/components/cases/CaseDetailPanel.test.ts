import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CaseDetailPanel from '../../../src/components/cases/CaseDetailPanel.vue'
import type { CaseDetailResponse } from '../../../src/api/cases'

const sample: CaseDetailResponse = {
  case_id: 'case-abc',
  problem_description: '顾客投诉上菜慢',
  store_profile: {
    store_id: 'st-1',
    store_name: '旗舰店',
    brand_id: 'br-1',
    brand_name: '测试品牌',
    business_type: '餐饮',
    store_scale: 'medium',
    franchise_type: 'direct',
    city: '北京',
    city_tier: 'tier1',
  },
  problem_type: 'product_quality',
  context: { scene: '晚市高峰', extra_note: '靠窗位' },
  root_cause: '后厨产能不足',
  solution_steps: [{ order: 1, content: '预制备菜' }],
  outcome: { result: 'no_change', notes: '观察中' },
  status: 'active',
  created_at: '2026-03-01T08:00:00Z',
  updated_at: '2026-03-02T09:00:00Z',
  tag_suggestions: [],
}

describe('CaseDetailPanel', () => {
  it('应渲染契约内基础字段且不输出向量类占位', () => {
    const w = mount(CaseDetailPanel, { props: { detail: sample } })
    const html = w.html()
    expect(html).toContain('顾客投诉上菜慢')
    expect(html).toContain('晚市高峰')
    expect(html).toContain('后厨产能不足')
    expect(html).toContain('预制备菜')
    expect(html).toContain('观察中')
    expect(html).toContain('case-abc')
    expect(html).toContain('测试品牌')
    expect(html).toContain('旗舰店')
    expect(html).not.toContain('embedding')
    expect(html).not.toContain('vector')
  })

  it('标签为空时显示占位符', () => {
    const w = mount(CaseDetailPanel, { props: { detail: sample } })
    expect(w.text()).toContain('标签')
    expect(w.text()).toContain('—')
  })

  it('标签区使用契约字段 tag_suggestions', () => {
    const w = mount(CaseDetailPanel, {
      props: {
        detail: { ...sample, tag_suggestions: ['客诉', '卫生'] },
      },
    })
    expect(w.text()).toContain('客诉')
    expect(w.text()).toContain('卫生')
  })
})
