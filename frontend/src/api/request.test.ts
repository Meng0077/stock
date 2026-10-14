import { afterEach, describe, expect, it, vi } from 'vitest'

import { post, request, requestResponse } from './request'
import { RequestError } from './requestErrors'


afterEach(() => {
  vi.unstubAllGlobals()
})


describe('request', () => {
  it('POST 序列化 JSON 并解析响应', async () => {
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, _options?: RequestInit) => new Response(
        JSON.stringify({ thread_id: 'thread-1', status: 'accepted' }),
        { headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const response = await post<
      { thread_id: string; status: 'accepted' },
      { message: string }
    >('/api/research', { message: 'NVDA 怎么看' })

    expect(response).toEqual({ thread_id: 'thread-1', status: 'accepted' })
    const options = fetchMock.mock.calls[0][1]
    if (!options) throw new Error('fetch options are missing')
    expect(options.method).toBe('POST')
    expect(options.body).toBe(JSON.stringify({ message: 'NVDA 怎么看' }))
    expect(new Headers(options.headers).get('Content-Type')).toBe('application/json')
    expect(new Headers(options.headers).get('Accept')).toBe('application/json')
  })

  it('相同 GET 共享一次底层请求', async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ value: 1 }),
      { headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const first = request<{ value: number }>('/api/shared')
    const second = request<{ value: number }>('/api/shared')

    await expect(first).resolves.toEqual({ value: 1 })
    await expect(second).resolves.toEqual({ value: 1 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('所有订阅者取消后取消共享底层请求', async () => {
    let fetchSignal: AbortSignal | undefined
    const fetchMock = vi.fn((_url: string | URL | Request, options?: RequestInit) => {
      fetchSignal = options?.signal ?? undefined
      return new Promise<Response>((_resolve, reject) => {
        fetchSignal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'))
        })
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const firstController = new AbortController()
    const secondController = new AbortController()

    const first = requestResponse('/api/pending', {
      signal: firstController.signal,
      retries: 0,
    })
    const second = requestResponse('/api/pending', {
      signal: secondController.signal,
      retries: 0,
    })

    firstController.abort()
    expect(fetchSignal?.aborted).toBe(false)
    secondController.abort()
    expect(fetchSignal?.aborted).toBe(true)

    const results = await Promise.allSettled([first, second])
    expect(results.every(
      result => result.status === 'rejected' &&
        result.reason instanceof RequestError &&
        result.reason.kind === 'aborted',
    )).toBe(true)
  })

  it('非法 JSON 保留 invalid_response 错误分类', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('not-json')))

    await expect(request('/api/invalid-json')).rejects.toMatchObject({
      kind: 'invalid_response',
    })
  })
})
