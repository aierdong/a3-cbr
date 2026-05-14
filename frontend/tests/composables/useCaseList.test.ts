import { describe, it, expect, vi } from 'vitest'
import { nextTick } from 'vue'
import {
  useCaseList,
  caseListQueryFromFilters,
  type CaseListFilters,
} from '../../src/composables/useCases'
import type { CaseApiService } from '../../src/api/cases'
import type { CaseListItem, PaginatedCaseListResponse } from '../../src/api/cases'

function makeItem(id: string): CaseListItem {
  return {
    case_id: id,
    problem_description_preview: `预览 ${id}`,
    store_profile: {
      store_id: 's1',
      store_name: '门店一',
      brand_id: 'b1',
      brand_name: '品牌一',
      business_type: '餐饮',
      store_scale: 'small',
      franchise_type: 'direct',
      city: '上海',
      city_tier: 'tier1',
    },
    context: { scene: `场景 ${id}` },
    problem_type: 'other',
    status: 'draft',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
  }
}

describe('caseListQueryFromFilters', () => {
  it('应将创建时间 UI 字段映射为后端查询名 created_after / created_before', () => {
    const q = caseListQueryFromFilters(
      { created_from: '2026-01-01T00:00:00.000Z', created_to: '2026-01-31T00:00:00.000Z' },
      { limit: 20 }
    )
    expect(q.created_after).toBe('2026-01-01T00:00:00.000Z')
    expect(q.created_before).toBe('2026-01-31T00:00:00.000Z')
    expect(q.created_from).toBeUndefined()
    expect(q.created_to).toBeUndefined()
  })

  it('应在有游标时附带 cursor 对', () => {
    const q = caseListQueryFromFilters(
      {},
      {
        limit: 10,
        cursor_created_at: '2026-01-01T00:00:00Z',
        cursor_case_id: 'c-prev',
      }
    )
    expect(q.limit).toBe(10)
    expect(q.cursor_created_at).toBe('2026-01-01T00:00:00Z')
    expect(q.cursor_case_id).toBe('c-prev')
  })
})

describe('useCaseList', () => {
  it('首次加载应合并列表并暴露 hasNextPage', async () => {
    const page: PaginatedCaseListResponse = {
      items: [makeItem('a')],
      limit: 20,
      next_cursor_created_at: '2026-01-01T00:00:00Z',
      next_cursor_case_id: 'a',
      has_more: true,
      sort: 'created_at desc, case_id desc',
    }
    const list = vi.fn().mockResolvedValue({ ok: true, data: page })
    const api = { list } as unknown as CaseApiService

    const u = useCaseList(api)
    await u.loadInitial({})
    await nextTick()

    expect(list).toHaveBeenCalledWith(expect.objectContaining({ limit: 20 }))
    expect(u.items.value).toHaveLength(1)
    expect(u.hasNextPage.value).toBe(true)
    expect(u.listPhase.value).toBe('success')
  })

  it('筛选提交应使用品牌与状态等查询参数', async () => {
    const list = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        items: [],
        limit: 20,
        next_cursor_created_at: null,
        next_cursor_case_id: null,
        has_more: false,
        sort: 'created_at desc, case_id desc',
      } satisfies PaginatedCaseListResponse,
    })
    const api = { list } as unknown as CaseApiService
    const u = useCaseList(api)

    const filters: CaseListFilters = {
      brand_id: 'brand-x',
      status: 'active',
    }
    await u.loadInitial(filters)
    await nextTick()

    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({
        brand_id: 'brand-x',
        status: 'active',
      })
    )
  })

  it('空列表成功时应为 empty 相且仍暴露分页元数据', async () => {
    const emptyPage: PaginatedCaseListResponse = {
      items: [],
      limit: 20,
      next_cursor_created_at: null,
      next_cursor_case_id: null,
      has_more: false,
      sort: 'created_at desc, case_id desc',
    }
    const list = vi.fn().mockResolvedValue({ ok: true, data: emptyPage })
    const u = useCaseList({ list } as unknown as CaseApiService)

    await u.loadInitial({})
    await nextTick()

    expect(u.listPhase.value).toBe('empty')
    expect(u.lastPageMeta.value?.limit).toBe(20)
    expect(u.items.value).toHaveLength(0)
  })

  it('加载更多应追加行并传入上一页游标', async () => {
    const first: PaginatedCaseListResponse = {
      items: [makeItem('1')],
      limit: 20,
      next_cursor_created_at: '2026-01-01T00:00:00Z',
      next_cursor_case_id: '1',
      has_more: true,
      sort: 'created_at desc, case_id desc',
    }
    const second: PaginatedCaseListResponse = {
      items: [makeItem('2')],
      limit: 20,
      next_cursor_created_at: null,
      next_cursor_case_id: null,
      has_more: false,
      sort: 'created_at desc, case_id desc',
    }
    const list = vi.fn().mockResolvedValueOnce({ ok: true, data: first }).mockResolvedValueOnce({ ok: true, data: second })

    const u = useCaseList({ list } as unknown as CaseApiService)
    await u.loadInitial({})
    await nextTick()
    await u.loadMore()
    await nextTick()

    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({
        cursor_created_at: '2026-01-01T00:00:00Z',
        cursor_case_id: '1',
      })
    )
    expect(u.items.value.map((r) => r.case_id)).toEqual(['1', '2'])
    expect(u.hasNextPage.value).toBe(false)
  })
})
