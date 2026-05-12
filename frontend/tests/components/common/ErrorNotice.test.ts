import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ErrorNotice from '../../../src/components/common/ErrorNotice.vue'

describe('ErrorNotice', () => {
  it('应展示稳定提示文案', () => {
    const wrapper = mount(ErrorNotice, {
      props: { message: '请求失败，请稍后重试' }
    })
    expect(wrapper.text()).toContain('请求失败')
  })

  it('showRetry 时应展示重试并触发 retry 事件', async () => {
    const wrapper = mount(ErrorNotice, {
      props: { message: '出错', showRetry: true }
    })
    const btn = wrapper.find('[data-testid="error-retry"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('retry')).toBeTruthy()
  })

  it('默认不展示重试按钮', () => {
    const wrapper = mount(ErrorNotice, {
      props: { message: '仅提示' }
    })
    expect(wrapper.find('[data-testid="error-retry"]').exists()).toBe(false)
  })
})
