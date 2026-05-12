import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from '../../../src/components/common/EmptyState.vue'

describe('EmptyState', () => {
  it('应展示自定义标题与描述', () => {
    const wrapper = mount(EmptyState, {
      props: {
        title: '没有找到案例',
        description: '请调整筛选条件后重试'
      }
    })
    expect(wrapper.text()).toContain('没有找到案例')
    expect(wrapper.text()).toContain('请调整筛选条件后重试')
  })

  it('应使用默认标题当未提供 title prop', () => {
    const wrapper = mount(EmptyState)
    expect(wrapper.text()).toContain('暂无数据')
  })

  it('应渲染操作插槽', () => {
    const wrapper = mount(EmptyState, {
      props: { title: '空' },
      slots: { action: '<button type="button">返回</button>' }
    })
    expect(wrapper.find('button').text()).toBe('返回')
  })
})
