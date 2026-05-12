import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import AdminLayout from '../../../src/components/layout/AdminLayout.vue'

describe('AdminLayout', () => {
  const Root = { template: '<router-view />' }

  const createTestRouter = () =>
    createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/cases',
          component: AdminLayout,
          children: [
            {
              path: '',
              name: 'case-list',
              meta: { breadcrumb: '案例管理 / 案例列表' },
              component: { template: '<div class="test-content">测试内容</div>' }
            },
            {
              path: 'create',
              name: 'case-create',
              meta: { breadcrumb: '案例管理 / 创建案例' },
              component: { template: '<div>Create</div>' }
            },
            {
              path: ':id/edit',
              name: 'case-edit',
              meta: { breadcrumb: '案例管理 / 编辑案例' },
              component: { template: '<div>Edit</div>' }
            },
            {
              path: ':id',
              name: 'case-detail',
              meta: { breadcrumb: '案例管理 / 案例详情' },
              component: { template: '<div>Detail</div>' }
            }
          ]
        },
        {
          path: '/recommendations',
          component: AdminLayout,
          children: [
            {
              path: '',
              name: 'recommendations',
              meta: { breadcrumb: '检索推荐 / 相似案例检索' },
              component: { template: '<div>Recommendations</div>' }
            }
          ]
        }
      ]
    })

  const mountWithRoute = async (path: string) => {
    const router = createTestRouter()
    router.push(path)
    await router.isReady()
    const wrapper = mount(Root, {
      global: { plugins: [router] }
    })
    await flushPromises()
    return { wrapper, router }
  }

  it('应该渲染案例管理导航入口', async () => {
    const { wrapper } = await mountWithRoute('/cases')
    const layout = wrapper.findComponent(AdminLayout)
    expect(layout.exists()).toBe(true)
    expect(layout.text()).toContain('案例管理')
  })

  it('应该渲染检索推荐导航入口', async () => {
    const { wrapper } = await mountWithRoute('/recommendations')
    const layout = wrapper.findComponent(AdminLayout)
    expect(layout.exists()).toBe(true)
    expect(layout.text()).toContain('检索推荐')
  })

  it('应该不展示越界菜单入口', async () => {
    const { wrapper } = await mountWithRoute('/cases')
    const layout = wrapper.findComponent(AdminLayout)
    expect(layout.text()).not.toContain('经营看板')
    expect(layout.text()).not.toContain('消息推送')
    expect(layout.text()).not.toContain('权限配置')
    expect(layout.text()).not.toContain('行业库审核')
  })

  it('应该在主区域渲染嵌套子路由页面', async () => {
    const { wrapper } = await mountWithRoute('/cases')
    expect(wrapper.find('.test-content').exists()).toBe(true)
    expect(wrapper.text()).toContain('测试内容')
  })

  it('应该在案例列表路由时高亮案例管理导航', async () => {
    const { wrapper } = await mountWithRoute('/cases')
    const layout = wrapper.findComponent(AdminLayout)
    const caseNav = layout.find('[data-nav="cases"]')
    expect(caseNav.exists()).toBe(true)
    expect(caseNav.classes()).toContain('active')
  })

  it('应该在推荐路由时高亮检索推荐导航', async () => {
    const { wrapper } = await mountWithRoute('/recommendations')
    const layout = wrapper.findComponent(AdminLayout)
    const recommendationNav = layout.find('[data-nav="recommendations"]')
    expect(recommendationNav.exists()).toBe(true)
    expect(recommendationNav.classes()).toContain('active')
  })

  it('应该在检索推荐页展示返回案例管理的面包屑入口（需求 1.2、5.1 闭环）', async () => {
    const { wrapper } = await mountWithRoute('/recommendations')
    const layout = wrapper.findComponent(AdminLayout)
    const toCases = layout.find('[data-testid="breadcrumb-to-cases"]')
    expect(toCases.exists()).toBe(true)
    expect(toCases.text()).toContain('案例管理')
    expect(toCases.attributes('href')).toContain('/cases')
  })

  it('应该在案例新建页展示返回列表入口', async () => {
    const { wrapper } = await mountWithRoute('/cases/create')
    const layout = wrapper.findComponent(AdminLayout)
    const back = layout.find('.breadcrumb-back')
    expect(back.exists()).toBe(true)
    expect(back.text()).toContain('返回列表')
    expect(layout.find('.breadcrumb-text').text()).toContain('创建案例')
  })
})
