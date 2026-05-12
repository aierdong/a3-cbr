import { describe, it, expect } from 'vitest'
import { nextTick } from 'vue'
import { useAsyncState } from '../../src/composables/useAsyncState'
import type { ApiResult } from '../../src/api/errors'

describe('useAsyncState', () => {
  it('初始为 idle', () => {
    const s = useAsyncState<{ n: number }>()
    expect(s.phase.value).toBe('idle')
    expect(s.data.value).toBeNull()
    expect(s.apiError.value).toBeNull()
  })

  it('run：成功时有 data，phase 为 success', async () => {
    const s = useAsyncState<{ n: number }>()
    const p = s.run(async () => ({ ok: true, data: { n: 1 } } as ApiResult<{ n: number }>))
    expect(s.phase.value).toBe('loading')
    await p
    await nextTick()
    expect(s.phase.value).toBe('success')
    expect(s.data.value).toEqual({ n: 1 })
    expect(s.successVariant.value).toBe('complete')
  })

  it('run：isEmpty 为真时进入 empty', async () => {
    const s = useAsyncState<number[]>({
      isEmpty: (d) => d.length === 0
    })
    await s.run(async () => ({ ok: true, data: [] } as ApiResult<number[]>))
    await nextTick()
    expect(s.phase.value).toBe('empty')
    expect(s.data.value).toEqual([])
  })

  it('run：降级成功应保持 success 且标记 degraded', async () => {
    type R = { status: string }
    const s = useAsyncState<R>({
      isDegradedSuccess: (d) => d.status === 'degraded'
    })
    await s.run(async () => ({ ok: true, data: { status: 'degraded' } } as ApiResult<R>))
    await nextTick()
    expect(s.phase.value).toBe('success')
    expect(s.successVariant.value).toBe('degraded')
  })

  it('run：Api 失败时应进入 error 并暴露 errorKind', async () => {
    const s = useAsyncState<unknown>()
    await s.run(async () => ({
      ok: false,
      error: {
        status: 404,
        code: 'CASE_NOT_FOUND',
        message: '案例不存在',
        kind: 'not_found'
      }
    }))
    await nextTick()
    expect(s.phase.value).toBe('error')
    expect(s.errorKind.value).toBe('not_found')
    expect(s.apiError.value?.code).toBe('CASE_NOT_FOUND')
  })

  it('校验失败应映射为 validation errorKind', async () => {
    const s = useAsyncState<unknown>()
    await s.run(async () => ({
      ok: false,
      error: {
        status: 422,
        code: 'VALIDATION_ERROR',
        message: '无效',
        kind: 'validation',
        fields: [{ field: 'x', message: 'bad' }]
      }
    }))
    await nextTick()
    expect(s.phase.value).toBe('error')
    expect(s.errorKind.value).toBe('validation')
  })

  it('reset 应回到 idle', async () => {
    const s = useAsyncState<{ n: number }>()
    await s.run(async () => ({ ok: true, data: { n: 1 } } as ApiResult<{ n: number }>))
    await nextTick()
    s.reset()
    expect(s.phase.value).toBe('idle')
    expect(s.data.value).toBeNull()
  })
})
