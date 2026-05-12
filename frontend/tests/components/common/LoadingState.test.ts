import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LoadingState from '../../../src/components/common/LoadingState.vue'

describe('LoadingState', () => {
  it('应展示 message 文案', () => {
    const wrapper = mount(LoadingState, { props: { message: '加载中…' } })
    expect(wrapper.text()).toContain('加载中')
  })

  it('应渲染默认插槽内容', () => {
    const wrapper = mount(LoadingState, {
      slots: { default: '<span class="slot-x">自定义</span>' }
    })
    expect(wrapper.find('.slot-x').exists()).toBe(true)
  })
})
