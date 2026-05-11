import { describe, it, expect } from 'vitest'
import router from '../../src/router'

describe('Router Configuration', () => {
  it('应该配置案例列表路由', () => {
    // 需求 1.1, 1.2: 案例列表页面路由
    const route = router.resolve({ name: 'case-list' })
    expect(route.name).toBe('case-list')
    expect(route.path).toBe('/cases')
  })

  it('应该配置案例创建路由', () => {
    // 需求 1.1, 1.2: 案例创建页面路由
    const route = router.resolve({ name: 'case-create' })
    expect(route.name).toBe('case-create')
    expect(route.path).toBe('/cases/create')
  })

  it('应该配置案例详情路由', () => {
    // 需求 1.1, 1.2: 案例详情页面路由
    const route = router.resolve({ name: 'case-detail', params: { id: '123' } })
    expect(route.name).toBe('case-detail')
    expect(route.path).toBe('/cases/123')
  })

  it('应该配置案例编辑路由', () => {
    // 需求 1.1, 1.2: 案例编辑页面路由
    const route = router.resolve({ name: 'case-edit', params: { id: '123' } })
    expect(route.name).toBe('case-edit')
    expect(route.path).toBe('/cases/123/edit')
  })

  it('应该配置推荐检索路由', () => {
    // 需求 1.1, 1.2: 推荐检索页面路由
    const route = router.resolve({ name: 'recommendations' })
    expect(route.name).toBe('recommendations')
    expect(route.path).toBe('/recommendations')
  })

  it('应该将根路径重定向到案例列表', async () => {
    // 需求 1.1: 基础导航入口 — `/` 重定向到案例列表
    await router.push('/')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('case-list')
    expect(router.currentRoute.value.path).toBe('/cases')
  })
})
