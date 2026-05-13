import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CaseForm from '../../../src/components/cases/CaseForm.vue'
import type { CaseDetailResponse } from '../../../src/api/cases'

const detail: CaseDetailResponse = {
  case_id: 'cid-1',
  problem_description: '问题全文',
  store_profile: {
    store_id: 's99',
    store_name: '门店',
    brand_id: 'b9',
    brand_name: '品牌',
    business_type: '餐饮',
    store_scale: 'small',
    franchise_type: 'direct',
    city: '沪',
    city_tier: 'tier1',
  },
  problem_type: 'operations',
  context: { scene: '场景A' },
  root_cause: '根因',
  solution_steps: [{ order: 1, content: '步骤一' }],
  outcome: { result: 'unknown', notes: '' },
  status: 'draft',
  created_at: '2026-01-10T00:00:00Z',
  updated_at: '2026-01-11T00:00:00Z',
  tag_suggestions: [],
}

describe('CaseForm', () => {
  it('创建模式「提交且摘要」应发出 active 状态与 meta', async () => {
    const w = mount(CaseForm, { props: { mode: 'create' } })
    await w.get('[data-testid="input-problem"]').setValue('新问题描述')
    await w.get('[data-testid="input-store-id"]').setValue('store-x')
    await w.get('[data-testid="input-scene"]').setValue('营业现场')
    await w.get('[data-testid="input-root-cause"]').setValue('根因说明')
    await w.get('[data-testid="input-solution-steps"]').setValue('解决动作')
    await w.get('[data-testid="submit-with-summary"]').trigger('click')
    await flushPromises()
    const ev = w.emitted('submit')
    expect(ev).toBeTruthy()
    const meta = ev![0][1] as { intent: string }
    expect(meta.intent).toBe('submit-with-summary')
    const payload = ev![0][0] as Record<string, unknown>
    expect(payload.status).toBe('active')
  })

  it('创建模式「创建并关闭」应发出 active 状态与 meta', async () => {
    const w = mount(CaseForm, { props: { mode: 'create' } })
    await w.get('[data-testid="input-problem"]').setValue('新问题描述')
    await w.get('[data-testid="input-store-id"]').setValue('store-x')
    await w.get('[data-testid="input-scene"]').setValue('营业现场')
    await w.get('[data-testid="input-root-cause"]').setValue('根因说明')
    await w.get('[data-testid="input-solution-steps"]').setValue('解决动作')
    await w.get('[data-testid="select-problem-type"]').setValue('safety_hygiene')
    await w.get('[data-testid="select-outcome-result"]').setValue('improved')
    await w.get('[data-testid="input-outcome-notes"]').setValue('效果好')
    await w.get('[data-testid="submit-save-and-close"]').trigger('click')
    await flushPromises()
    const ev = w.emitted('submit')
    expect(ev).toBeTruthy()
    const payload = ev![0][0] as Record<string, unknown>
    const meta = ev![0][1] as { intent: string }
    expect(meta.intent).toBe('save-and-close')
    expect(payload).not.toHaveProperty('case_id')
    expect(payload).not.toHaveProperty('created_at')
    expect(payload.status).toBe('active')
    expect(payload.problem_description).toBe('新问题描述')
    expect(payload.store_id).toBe('store-x')
    expect(payload.problem_type).toBe('safety_hygiene')
    expect(payload.root_cause).toBe('根因说明')
    expect(payload.context).toEqual({ scene: '营业现场' })
    expect(payload.solution_steps).toEqual([{ order: 1, content: '解决动作' }])
    expect(payload.outcome).toEqual({ result: 'improved', notes: '效果好' })
  })

  it('解决步骤多行文本应按行解析为 solution_steps 数组', async () => {
    const w = mount(CaseForm, { props: { mode: 'create' } })
    await w.get('[data-testid="input-problem"]').setValue('新问题描述')
    await w.get('[data-testid="input-store-id"]').setValue('store-x')
    await w.get('[data-testid="input-scene"]').setValue('营业现场')
    await w.get('[data-testid="input-root-cause"]').setValue('根因说明')
    await w.get('[data-testid="input-solution-steps"]').setValue('第一步\n第二步\n')
    await w.get('[data-testid="submit-save-and-close"]').trigger('click')
    await flushPromises()
    const payload = w.emitted('submit')![0][0] as Record<string, unknown>
    expect(payload.solution_steps).toEqual([
      { order: 1, content: '第一步' },
      { order: 2, content: '第二步' },
    ])
  })

  it('创建模式「存为草稿」应发出 draft 状态与 meta', async () => {
    const w = mount(CaseForm, { props: { mode: 'create' } })
    await w.get('[data-testid="input-problem"]').setValue('新问题描述')
    await w.get('[data-testid="input-store-id"]').setValue('store-x')
    await w.get('[data-testid="input-scene"]').setValue('营业现场')
    await w.get('[data-testid="input-root-cause"]').setValue('根因说明')
    await w.get('[data-testid="input-solution-steps"]').setValue('解决动作')
    await w.get('[data-testid="submit-save-draft"]').trigger('click')
    await flushPromises()
    const ev = w.emitted('submit')
    expect(ev).toBeTruthy()
    const payload = ev![0][0] as Record<string, unknown>
    const meta = ev![0][1] as { intent: string }
    expect(meta.intent).toBe('save-draft')
    expect(payload.status).toBe('draft')
  })

  it('编辑模式应展示只读案例标识与创建时间且「保存并关闭」提交 active', async () => {
    const w = mount(CaseForm, { props: { mode: 'edit', initialDetail: detail } })
    await flushPromises()
    expect(w.text()).toContain('cid-1')
    expect(w.text()).toContain('2026-01-10')
    const idInput = w.find('[data-testid="readonly-case-id"]')
    expect(idInput.exists()).toBe(true)
    expect(w.find('[data-testid="input-problem"]').element).toBeTruthy()
    await w.get('[data-testid="submit-save-and-close"]').trigger('click')
    await flushPromises()
    const payload = w.emitted('submit')![0][0] as Record<string, unknown>
    const meta = w.emitted('submit')![0][1] as { intent: string }
    expect(meta.intent).toBe('save-and-close')
    expect(payload).not.toHaveProperty('case_id')
    expect(payload).not.toHaveProperty('created_at')
    expect(payload.status).toBe('active')
  })

  it('编辑模式「存为草稿」应提交 status 为 draft', async () => {
    const w = mount(CaseForm, { props: { mode: 'edit', initialDetail: detail } })
    await flushPromises()
    await w.get('[data-testid="submit-save-draft"]').trigger('click')
    await flushPromises()
    const payload = w.emitted('submit')![0][0] as Record<string, unknown>
    expect(payload.status).toBe('draft')
  })

  it('应在对应字段下展示字段级错误', async () => {
    const w = mount(CaseForm, {
      props: {
        mode: 'create',
        fieldErrors: { store_id: '门店不存在', 'solution_steps.0.content': '步骤不能为空' },
      },
    })
    await flushPromises()
    expect(w.text()).toContain('门店不存在')
    expect(w.text()).toContain('第 1 步')
    expect(w.text()).toContain('步骤不能为空')
  })
})
