/**
 * 任务 5.3：案例列表空状态与分页元数据展示（需求 2.3）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CaseListPage from '../../src/pages/CaseListPage.vue'

const apiClient = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}))

vi.mock('../../src/api/client', () => ({
  createApiClient: vi.fn(() => apiClient),
}))

describe('CaseListPage', () => {
  beforeEach(() => {
    apiClient.get.mockReset()
    apiClient.get.mockResolvedValue({
      ok: true,
      data: {
        items: [],
        limit: 20,
        next_cursor_created_at: null,
        next_cursor_case_id: null,
        has_more: false,
        sort: 'created_at desc, case_id desc',
      },
    })
  })

  it('空列表成功时应展示空状态与分页元信息', async () => {
    const w = mount(CaseListPage, {
      global: {
        stubs: { RouterLink: true },
      },
    })
    await flushPromises()

    expect(apiClient.get).toHaveBeenCalled()
    expect(w.text()).toContain('暂无匹配案例')
    expect(w.find('[data-testid="empty-page-meta"]').exists()).toBe(true)
    expect(w.find('[data-testid="empty-page-meta"]').text()).toContain('每页 20 条')
  })
})
