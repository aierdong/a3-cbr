import { describe, it, expect, vi } from 'vitest'
import { createCaseApiService } from '../../src/api/cases'
import type { ApiClient } from '../../src/api/client'

function mockClient(partial: Partial<ApiClient>): ApiClient {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    ...partial,
  }
}

const emptyList = {
  items: [],
  limit: 20,
  next_cursor_created_at: null,
  next_cursor_case_id: null,
  has_more: false,
  sort: 'created_at desc, case_id desc' as const,
}

describe('createCaseApiService', () => {
  it('list 应对 /api/a3-cases 发起 GET 并传递查询参数', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: emptyList })
    const api = createCaseApiService(mockClient({ get }))
    await api.list({ brand_id: 'b1', limit: 10 })
    expect(get).toHaveBeenCalledWith('/api/a3-cases', { brand_id: 'b1', limit: 10 })
  })

  it('create 应对 /api/a3-cases 发起 POST 且请求体为契约类型', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createCaseApiService(mockClient({ post }))
    const body = {
      problem_description: '问题',
      store_id: 'store-1',
      problem_type: 'other' as const,
      context: { scene: '门店' },
      root_cause: '根因',
      solution_steps: [{ order: 1, content: '步骤' }],
      outcome: { result: 'unknown' as const, notes: '备注' },
    }
    await api.create(body)
    expect(post).toHaveBeenCalledWith('/api/a3-cases', body)
  })

  it('getById 应对编码后的 case_id 发起 GET', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createCaseApiService(mockClient({ get }))
    await api.getById('case/01')
    expect(get).toHaveBeenCalledWith('/api/a3-cases/case%2F01')
  })

  it('update 应对 PUT /api/a3-cases/{id}', async () => {
    const put = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createCaseApiService(mockClient({ put }))
    const patch = { status: 'active' as const }
    await api.update('c1', patch)
    expect(put).toHaveBeenCalledWith('/api/a3-cases/c1', patch)
  })
})
