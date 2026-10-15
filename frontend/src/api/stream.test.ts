import { afterEach, describe, expect, it, vi } from 'vitest'

import { stream, type SseEvent } from './stream'


const encoder = new TextEncoder()


function eventStream(text: string): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(text))
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}


function pendingEventStream(): Response {
  return new Response(
    new ReadableStream({ start() {} }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}


afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})


describe('stream reconnect', () => {
  it('断线后携带最后消费的 Last-Event-ID 并继续交付事件', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(eventStream('id: 1\nevent: answer_delta\ndata: first\n\n'))
      .mockResolvedValueOnce(eventStream('id: 2\nevent: completed\ndata: done\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    const received: SseEvent[] = []

    await stream('/events', {
      connectTimeout: 0,
      idleTimeout: 0,
      reconnectDelay: 0,
      maxReconnectDelay: 0,
      onEvent(event) {
        received.push(event)
        return event.event !== 'completed'
      },
    })

    expect(received.map(event => event.id)).toEqual(['1', '2'])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const reconnectHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers)
    expect(reconnectHeaders.get('Last-Event-ID')).toBe('1')
  })

  it('超过最大重连次数后抛出网络错误', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn(async () => eventStream(''))
    vi.stubGlobal('fetch', fetchMock)

    await expect(stream('/events', {
      connectTimeout: 0,
      idleTimeout: 0,
      reconnectDelay: 0,
      maxReconnectDelay: 0,
      maxReconnects: 2,
      onEvent: () => true,
    })).rejects.toMatchObject({ kind: 'network' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('409 history unavailable 不继续重连', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(eventStream('id: 1\ndata: first\n\n'))
      .mockResolvedValueOnce(new Response(null, { status: 409 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(stream('/events', {
      connectTimeout: 0,
      idleTimeout: 0,
      reconnectDelay: 0,
      maxReconnectDelay: 0,
      onEvent: () => true,
    })).rejects.toMatchObject({ kind: 'http', status: 409 })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('用户主动 abort 后不重连', async () => {
    const fetchMock = vi.fn((_url: string | URL | Request, options?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'))
        })
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const streaming = stream('/events', {
      signal: controller.signal,
      onEvent: () => true,
    })

    controller.abort()

    await expect(streaming).rejects.toMatchObject({ kind: 'aborted' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('idle timeout 作为可恢复错误触发重连', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(pendingEventStream())
      .mockResolvedValueOnce(eventStream('id: 1\nevent: completed\ndata: done\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    const streaming = stream('/events', {
      connectTimeout: 0,
      idleTimeout: 10,
      reconnectDelay: 0,
      maxReconnectDelay: 0,
      onEvent: event => event.event !== 'completed',
    })

    await vi.advanceTimersByTimeAsync(11)
    await streaming

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('heartbeat 注释保持连接且不产生业务事件', async () => {
    const fetchMock = vi.fn(async () => eventStream(
      ': heartbeat\n\nid: 1\nevent: completed\ndata: done\n\n',
    ))
    vi.stubGlobal('fetch', fetchMock)
    const received: SseEvent[] = []

    await stream('/events', {
      connectTimeout: 0,
      idleTimeout: 10,
      onEvent(event) {
        received.push(event)
        return false
      },
    })

    expect(received).toEqual([{ id: '1', event: 'completed', data: 'done' }])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
