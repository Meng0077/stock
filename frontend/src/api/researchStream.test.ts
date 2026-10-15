import { afterEach, describe, expect, it, vi } from 'vitest'

import { RequestError } from './requestErrors'
import { subscribeResearchEvents } from './researchStream'
import { stream } from './stream'


vi.mock('./stream', () => ({
  stream: vi.fn(),
}))


const streamMock = vi.mocked(stream)

const event = (overrides: Record<string, unknown> = {}) => ({
  thread_id: 'thread-1',
  event_id: 1,
  type: 'workflow_started',
  data: { execution: 'start' },
  created_at: '2026-10-14T12:00:00Z',
  ...overrides,
})


afterEach(() => {
  streamMock.mockReset()
})


describe('subscribeResearchEvents', () => {
  it('订阅后端 Research SSE 路径并传递事件', async () => {
    const received: unknown[] = []
    streamMock.mockImplementation(async (_url, options) => {
      const keepGoing = await options.onEvent({
        id: '1',
        event: 'workflow_started',
        data: JSON.stringify(event()),
      })
      expect(keepGoing).toBe(true)
    })

    await subscribeResearchEvents(
      'thread-1',
      researchEvent => received.push(researchEvent),
      new AbortController().signal,
    )

    expect(streamMock).toHaveBeenCalledWith(
      '/api/research/thread-1/events',
      expect.objectContaining({ connectionKey: 'research:thread-1' }),
    )
    expect(received).toEqual([event()])
  })

  it.each(['completed', 'failed', 'cancelled'] as const)('%s 终态事件返回 false 结束 SSE', async (type) => {
    streamMock.mockImplementation(async (_url, options) => {
      await expect(options.onEvent({
        id: '2',
        event: type,
        data: JSON.stringify(event({
          event_id: 2,
          type,
          data: type === 'completed' ? { result: 'done' } : {},
        })),
      })).resolves.toBe(false)
    })

    await subscribeResearchEvents(
      'thread-1',
      () => undefined,
      new AbortController().signal,
    )
  })

  it('拒绝其他 thread 或非法事件', async () => {
    streamMock.mockImplementation(async (_url, options) => {
      await options.onEvent({
        id: '1',
        event: 'workflow_started',
        data: JSON.stringify(event({ thread_id: 'thread-2' })),
      })
    })

    await expect(subscribeResearchEvents(
      'thread-1',
      () => undefined,
      new AbortController().signal,
    )).rejects.toBeInstanceOf(RequestError)
  })

  it('拒绝未知的研究事件类型', async () => {
    streamMock.mockImplementation(async (_url, options) => {
      await options.onEvent({
        id: '1',
        event: 'unknown',
        data: JSON.stringify(event({ type: 'unknown' })),
      })
    })

    await expect(subscribeResearchEvents(
      'thread-1',
      () => undefined,
      new AbortController().signal,
    )).rejects.toBeInstanceOf(RequestError)
  })
})
