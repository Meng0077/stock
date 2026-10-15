import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ResearchEvent } from '../../api/contracts'
import { useResearchRun } from './useResearchRun'


const mocks = vi.hoisted(() => ({
  startResearch: vi.fn(),
  subscribeResearchEvents: vi.fn(),
}))


vi.mock('../../api/runTransport', () => ({
  startResearch: mocks.startResearch,
}))

vi.mock('../../api/researchStream', () => ({
  subscribeResearchEvents: mocks.subscribeResearchEvents,
}))


const researchEvent = (
  type: ResearchEvent['type'],
  data: Record<string, unknown> = {},
  eventId = 1,
): ResearchEvent => ({
  thread_id: 'thread-1',
  event_id: eventId,
  type,
  data,
  created_at: '2026-10-14T12:00:00Z',
})


beforeEach(() => {
  mocks.startResearch.mockReset()
  mocks.subscribeResearchEvents.mockReset()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    return window.setTimeout(() => callback(0), 0)
  })
  vi.stubGlobal('cancelAnimationFrame', (frameId: number) => {
    window.clearTimeout(frameId)
  })
})


afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})


describe('useResearchRun', () => {
  it('绑定服务端 thread 并按 SSE 事件完成一轮研究', async () => {
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started'))
        onEvent(researchEvent('stage_changed', { stage: 'answering' }, 2))
        onEvent(researchEvent('answer_delta', { text: 'NVDA' }, 3))
        onEvent(researchEvent('completed', { result: 'NVDA' }, 4))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: '  NVDA 怎么看  ' })
    })

    expect(mocks.startResearch).toHaveBeenCalledWith(
      { message: 'NVDA 怎么看' },
      expect.any(AbortSignal),
    )
    expect(mocks.subscribeResearchEvents).toHaveBeenCalledWith(
      'thread-1',
      expect.any(Function),
      expect.any(AbortSignal),
    )
    expect(result.current.rounds).toEqual([{
      id: 1,
      threadId: 'thread-1',
      question: 'NVDA 怎么看',
      status: 'completed',
      contents: [{ type: 'text', text: 'NVDA' }],
      stage: null,
      errorMessage: null,
      clarification: null,
      clarificationSubmitting: false,
      clarificationErrorMessage: null,
      pendingClarificationAnswer: null,
    }])
  })

  it('启动请求失败时不订阅 SSE', async () => {
    mocks.startResearch.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(mocks.subscribeResearchEvents).not.toHaveBeenCalled()
    expect(result.current.rounds[0]).toMatchObject({
      threadId: null,
      status: 'request_failed',
      errorMessage: '暂时无法完成请求，请稍后重试。',
    })
  })

  it('SSE 失败时保留当前轮并标记 stream_failed', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockRejectedValue(new Error('disconnected'))
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      threadId: 'thread-1',
      status: 'stream_failed',
      errorMessage: '研究连接已中断，请稍后重试。',
    })
  })
})
