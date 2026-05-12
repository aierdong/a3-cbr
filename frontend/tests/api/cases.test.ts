import { describe, it, expect, vi } from 'vitest'
import {
  createCaseApiService,
  type CaseFieldError,
  type CaseListItem,
} from '../../src/api/cases'
import type { ApiClient } from '../../src/api/client'
import type { FieldError } from '../../src/api/errors'

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

  it('list 应传递 Keyset 游标参数 cursor_created_at 与 cursor_case_id', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: emptyList })
    const api = createCaseApiService(mockClient({ get }))
    await api.list({
      cursor_created_at: '2026-01-01T00:00:00Z',
      cursor_case_id: 'c-prev',
      limit: 20,
    })
    expect(get).toHaveBeenCalledWith('/api/a3-cases', {
      cursor_created_at: '2026-01-01T00:00:00Z',
      cursor_case_id: 'c-prev',
      limit: 20,
    })
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

  it('detail 应对编码后的 case_id 发起 GET', async () => {
    const get = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createCaseApiService(mockClient({ get }))
    await api.detail('case/01')
    expect(get).toHaveBeenCalledWith('/api/a3-cases/case%2F01')
  })

  it('update 应对 PUT /api/a3-cases/{id}', async () => {
    const put = vi.fn().mockResolvedValue({ ok: true, data: {} })
    const api = createCaseApiService(mockClient({ put }))
    const patch = { status: 'active' as const }
    await api.update('c1', patch)
    expect(put).toHaveBeenCalledWith('/api/a3-cases/c1', patch)
  })

  it('CaseFieldError 与 ApiError.fields 的 FieldError 结构一致（契约字段错误）', () => {
    const fe: CaseFieldError = { field: 'problem_description', message: '必填' }
    const asApiField: FieldError = fe
    expect(asApiField.field).toBe('problem_description')
  })

  it('CaseListItem 为列表项契约形状（含预览与门店档案）', () => {
    const row: CaseListItem = {
      case_id: 'c1',
      problem_description_preview: '预览…',
      store_profile: {
        store_id: 's1',
        store_name: '门店',
        brand_id: 'b1',
        brand_name: '品牌',
        business_type: '餐饮',
        store_scale: 'small',
        franchise_type: 'direct',
        city: '上海',
        city_tier: 'tier1',
      },
      problem_type: 'other',
      status: 'draft',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }
    expect(row.case_id).toBe('c1')
  })
})
