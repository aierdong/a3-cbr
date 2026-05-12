import { describe, it, expect, vi } from 'vitest'
import { nextTick } from 'vue'
import { useCaseDetail } from '../../src/composables/useCases'
import type { CaseApiService } from '../../src/api/cases'
import type { CaseDetailResponse } from '../../src/api/cases'

function makeDetail(id: string): CaseDetailResponse {
  return {
    case_id: id,
    problem_description: '完整问题',
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
    problem_type: 'service',
    context: { scene: '高峰排队' },
    root_cause: '人手不足',
    solution_steps: [
      { order: 1, content: '增派收银' },
      { order: 2, content: '引导分流' },
    ],
    outcome: { result: 'improved', notes: '排队缩短' },
    status: 'draft',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
  }
}

describe('useCaseDetail', () => {
  it('加载成功时应写入 detail 并进入 success 相', async () => {
    const detail = makeDetail('c-1')
    const d = vi.fn().mockResolvedValue({ ok: true, data: detail })
    const api = { detail: d } as unknown as CaseApiService
    const u = useCaseDetail(api)
    await u.loadDetail('c-1')
    await nextTick()
    expect(d).toHaveBeenCalledWith('c-1')
    expect(u.detailPhase.value).toBe('success')
    expect(u.detail.value?.case_id).toBe('c-1')
    expect(u.detailError.value).toBeNull()
  })

  it('加载失败时应暴露 error 相与 ApiError', async () => {
    const err = { kind: 'not_found' as const, code: 'CASE_NOT_FOUND', message: '不存在', status: 404 }
    const d = vi.fn().mockResolvedValue({ ok: false, error: err })
    const api = { detail: d } as unknown as CaseApiService
    const u = useCaseDetail(api)
    await u.loadDetail('missing')
    await nextTick()
    expect(u.detailPhase.value).toBe('error')
    expect(u.detail.value).toBeNull()
    expect(u.detailError.value).toEqual(err)
  })

  it('retryDetail 应使用最近一次 case_id 重新请求', async () => {
    const detail = makeDetail('c-2')
    const d = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, error: { kind: 'system', code: 'X', message: 'err', status: 500 } })
      .mockResolvedValueOnce({ ok: true, data: detail })
    const api = { detail: d } as unknown as CaseApiService
    const u = useCaseDetail(api)
    await u.loadDetail('c-2')
    expect(u.detailPhase.value).toBe('error')
    await u.retryDetail()
    await nextTick()
    expect(d).toHaveBeenCalledTimes(2)
    expect(u.detailPhase.value).toBe('success')
    expect(u.detail.value?.problem_description).toBe('完整问题')
  })
})
