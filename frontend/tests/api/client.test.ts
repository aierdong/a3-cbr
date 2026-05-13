import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createApiClient } from '../../src/api/client'

function jsonResponse(init: ResponseInit & { body?: unknown }) {
  const body = init.body !== undefined ? JSON.stringify(init.body) : ''
  return new Response(body, { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } })
}

describe('createApiClient', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('get：成功时应解析 JSON 并返回 ok: true', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(
      jsonResponse({ status: 200, body: { id: '1', name: 'x' } })
    )

    const client = createApiClient({ baseUrl: 'https://api.example' })
    const result = await client.get<{ id: string; name: string }>('/things')

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example/things',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Accept: 'application/json' })
      })
    )
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.data).toEqual({ id: '1', name: 'x' })
    }
  })

  it('get：应将 query 参数拼接到 URL', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: 200, body: {} }))

    const client = createApiClient({ baseUrl: '' })
    await client.get('/p', { a: '1', b: 2, skip: undefined, flag: false })

    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/^\/?\/p\?a=1&b=2&flag=false$|^\/p\?a=1&b=2&flag=false$/),
      expect.any(Object)
    )
  })

  it('post：可附加自定义请求头并与 Content-Type 合并', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: 200, body: { ok: true } }))

    const client = createApiClient({ baseUrl: '' })
    await client.post<unknown, { ok: boolean }>(
      '/api/recommendation-feedback',
      { recommendation_run_id: 'r1', usefulness: 'useful' },
      { headers: { 'X-Actor-Id': 'anonymous_user' } }
    )

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-Actor-Id': 'anonymous_user',
        }),
      })
    )
  })

  it('422 且含 fields：应映射为校验类 ApiError（含字段错误）且不携带 meta/raw body', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 422,
        body: {
          code: 'VALIDATION_ERROR',
          message: '字段无效',
          fields: [{ field: 'title', message: '必填' }],
          meta: { sensitive_dump: 'SECRET' }
        }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.post<unknown, unknown>('/', {})

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.status).toBe(422)
      expect(result.error.code).toBe('VALIDATION_ERROR')
      expect(result.error.message).toContain('字段')
      expect(result.error.kind).toBe('validation')
      expect(result.error.fields).toEqual([{ field: 'title', message: '必填' }])
      expect('meta' in result.error).toBe(false)
      expect('body' in result.error).toBe(false)
      expect(JSON.stringify(result.error)).not.toContain('SECRET')
    }
  })

  it('404：应为 not_found 分类', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 404,
        body: { code: 'CASE_NOT_FOUND', message: '案例不存在或已被删除' }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.get('/cases/x')

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('not_found')
      expect(result.error.code).toBe('CASE_NOT_FOUND')
    }
  })

  it('404：含 meta 的响应不得泄漏 meta 到 ApiError（需求 6.4）', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 404,
        body: {
          code: 'CASE_NOT_FOUND',
          message: '未找到',
          meta: { full_case_body: 'SECRET_BODY', embedding: [0.1, 0.2] },
        },
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.get('/cases/x')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect('meta' in result.error).toBe(false)
      expect(JSON.stringify(result.error)).not.toContain('SECRET_BODY')
      expect(JSON.stringify(result.error)).not.toContain('embedding')
    }
  })

  it('409：应为 conflict 分类', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 409,
        body: { code: 'CASE_STATE_CONFLICT', message: '状态冲突' }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.put<unknown, unknown>('/cases/x', {})

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('conflict')
    }
  })

  it('503：应为 dependency_unavailable 分类', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 503,
        body: { code: 'VECTOR_SEARCH_FAILED', message: '向量搜索服务暂时不可用' }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.post<unknown, unknown>('/run', {})

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('dependency_unavailable')
    }
  })

  it('500：应为 system 分类', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 500,
        body: { code: 'INTERNAL_ERROR', message: '系统异常' }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.get('/x')

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('system')
    }
  })

  it('400：应为 user_error 分类', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: 400,
        body: { code: 'STORE_NOT_FOUND', message: '门店不存在' }
      })
    )

    const client = createApiClient({ baseUrl: '' })
    const result = await client.post<unknown, unknown>('/x', {})

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('user_error')
    }
  })

  it('fetch 抛出：应返回 network 类错误', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    const client = createApiClient({ baseUrl: '' })
    const result = await client.get('/x')

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('network')
      expect(result.error.status).toBe(0)
    }
  })

  it('超时中止：应返回 REQUEST_TIMEOUT 与中文超时提示', async () => {
    vi.useFakeTimers()
    vi.mocked(fetch).mockImplementation((_url, init) => {
      return new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal as AbortSignal | undefined
        if (signal?.aborted) {
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        signal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    })

    const client = createApiClient({ baseUrl: '', timeout: 50 })
    const reqPromise = client.get('/x')
    await vi.advanceTimersByTimeAsync(100)
    const result = await reqPromise
    vi.useRealTimers()

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.kind).toBe('network')
      expect(result.error.code).toBe('REQUEST_TIMEOUT')
      expect(result.error.message).toContain('超时')
    }
  })
})
