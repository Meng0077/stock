import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ResearchEvent } from '../../api/contracts'
import { useResearchRun } from './useResearchRun'


const mocks = vi.hoisted(() => ({
  startResearch: vi.fn(),
  resumeResearch: vi.fn(),
  cancelResearch: vi.fn(),
  subscribeResearchEvents: vi.fn(),
}))


vi.mock('../../api/runTransport', () => ({
  startResearch: mocks.startResearch,
  resumeResearch: mocks.resumeResearch,
  cancelResearch: mocks.cancelResearch,
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


const clarificationData = {
  type: 'target_clarification',
  message: '请选择 Google 对应的股票。',
  ambiguous_targets: [{ mention: 'Google', candidates: ['GOOG', 'GOOGL'] }],
  unresolved_mentions: [],
}


beforeEach(() => {
  mocks.startResearch.mockReset()
  mocks.resumeResearch.mockReset()
  mocks.cancelResearch.mockReset()
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
  it('空字符串和纯空格不创建 Round 或请求', async () => {
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: '   ' })
    })

    expect(result.current.rounds).toEqual([])
    expect(mocks.startResearch).not.toHaveBeenCalled()
    expect(mocks.subscribeResearchEvents).not.toHaveBeenCalled()
  })

  it('正常提交后立即创建 submitting Round', async () => {
    let resolveStart: ((value: { thread_id: string; status: 'accepted' }) => void) | null = null
    mocks.startResearch.mockImplementation(() => new Promise(resolve => {
      resolveStart = resolve
    }))
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('completed', { result: '完成' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())
    let submitting: Promise<void> = Promise.resolve()

    act(() => {
      submitting = result.current.submit({ message: 'NVDA 怎么看' })
    })
    expect(result.current.rounds[0]).toMatchObject({
      question: 'NVDA 怎么看',
      threadId: null,
      status: 'submitting',
    })

    await act(async () => {
      resolveStart?.({ thread_id: 'thread-1', status: 'accepted' })
      await submitting
    })
  })

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

  it('没有 answer_delta 时使用 completed result 展示回答', async () => {
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('completed', { result: '完整回答' }, 2))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'completed',
      stage: null,
      contents: [{ type: 'text', text: '完整回答' }],
    })
  })

  it('drain 已收到的文字后展示后端公开错误', async () => {
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: '已展示内容' }, 2))
        onEvent(researchEvent('failed', { error: { message: '公开错误信息' } }, 3))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'failed',
      stage: null,
      errorMessage: '公开错误信息',
      contents: [{ type: 'text', text: '已展示内容' }],
    })
  })

  it('Queue 展示失败时进入 display_failed 并显示安全错误', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('requestAnimationFrame', () => {
      throw new Error('animation failed')
    })
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: 'NVDA' }, 2))
        onEvent(researchEvent('completed', { result: 'NVDA' }, 3))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'display_failed',
      errorMessage: '研究结果展示失败，请稍后重试。',
    })
  })

  it('Resume 后保留补充答案并创建新的回答文字段', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.resumeResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: '前半段' }, 2))
        onEvent(researchEvent('needs_input', clarificationData, 3))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'Google 怎么看' })
    })
    expect(result.current.rounds[0]).toMatchObject({
      status: 'needs_input',
      contents: [{ type: 'text', text: '前半段' }],
      clarification: clarificationData,
    })
    await act(async () => {
      await result.current.submitAnswer(1, ['GOOGL'])
    })

    expect(mocks.resumeResearch).toHaveBeenCalledWith(
      { thread_id: 'thread-1', answer: ['GOOGL'] },
      expect.any(AbortSignal),
    )
    expect(mocks.subscribeResearchEvents).toHaveBeenCalledTimes(1)

    act(() => {
      emitEvent?.(researchEvent('workflow_started', { execution: 'resume' }, 4))
      emitEvent?.(researchEvent('answer_delta', { text: '后半段' }, 5))
      emitEvent?.(researchEvent('completed', { result: '后半段' }, 6))
    })

    await waitFor(() => {
      expect(result.current.rounds[0]).toMatchObject({
        status: 'completed',
        clarification: null,
        pendingClarificationAnswer: null,
        contents: [
          { type: 'text', text: '前半段' },
          { type: 'clarification_answer', text: ['GOOGL'] },
          { type: 'text', text: '后半段' },
        ],
      })
    })
  })

  it('Resume 失败时保留 needs_input 并允许使用同一 thread 重试', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.resumeResearch
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ thread_id: 'thread-1', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('needs_input', clarificationData, 2))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'Google 怎么看' })
    })
    await act(async () => {
      await result.current.submitAnswer(1, ['GOOGL'])
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'needs_input',
      clarification: clarificationData,
      clarificationSubmitting: false,
      clarificationErrorMessage: '补充信息提交失败，请重试。',
      pendingClarificationAnswer: null,
    })

    await act(async () => {
      await result.current.submitAnswer(1, ['GOOG'])
    })

    expect(mocks.resumeResearch).toHaveBeenNthCalledWith(
      2,
      { thread_id: 'thread-1', answer: ['GOOG'] },
      expect.any(AbortSignal),
    )
    expect(mocks.subscribeResearchEvents).toHaveBeenCalledTimes(1)
    expect(result.current.rounds[0]).toMatchObject({
      status: 'needs_input',
      clarificationSubmitting: true,
      clarificationErrorMessage: null,
      pendingClarificationAnswer: ['GOOG'],
    })

    act(() => {
      emitEvent?.(researchEvent('workflow_started', { execution: 'resume' }, 3))
      emitEvent?.(researchEvent('answer_delta', { text: '重试后的回答' }, 4))
      emitEvent?.(researchEvent('completed', { result: '重试后的回答' }, 5))
    })
    await waitFor(() => {
      expect(result.current.rounds[0]).toMatchObject({
        status: 'completed',
        clarification: null,
        pendingClarificationAnswer: null,
        contents: [
          { type: 'clarification_answer', text: ['GOOG'] },
          { type: 'text', text: '重试后的回答' },
        ],
      })
    })
  })

  it('取消请求失败时恢复研究状态并生成可见提示消息', async () => {
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started'))
      },
    )
    mocks.cancelResearch.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    await act(async () => {
      await result.current.cancel(1)
    })

    expect(mocks.cancelResearch).toHaveBeenCalledWith(
      'thread-1',
      expect.any(AbortSignal),
    )
    expect(result.current.rounds[0].status).toBe('researching')
    expect(result.current.toastMessage).toBe('取消研究请求失败，请稍后重试。')
  })

  it('取消请求成功后等待 cancelled 事件进入终态', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    mocks.startResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'accepted',
    })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started'))
      },
    )
    mocks.cancelResearch.mockResolvedValue({
      thread_id: 'thread-1',
      status: 'cancelling',
    })
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    await act(async () => {
      await result.current.cancel(1)
    })

    expect(mocks.cancelResearch).toHaveBeenCalledWith(
      'thread-1',
      expect.any(AbortSignal),
    )
    expect(result.current.rounds[0].status).toBe('cancelling')

    act(() => {
      emitEvent?.(researchEvent('cancelled', {}, 2))
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'cancelled',
      stage: null,
    })
  })

  it('cancelled 立即停止动画并丢弃尚未展示的文字', async () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: 'AB' }, 2))
        await Promise.resolve()
        onEvent(researchEvent('cancelled', {}, 3))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'cancelled',
      stage: null,
      contents: [{ type: 'text', text: 'A' }],
    })
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })

  it('Queue 已记录 failure 时 cancelled 仍保持最终状态', async () => {
    vi.stubGlobal('requestAnimationFrame', () => {
      throw new Error('animation failed')
    })
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: 'AB' }, 2))
        await Promise.resolve()
        onEvent(researchEvent('cancelled', {}, 3))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })

    expect(result.current.rounds[0]).toMatchObject({
      status: 'cancelled',
      stage: null,
    })
  })

  it('取消失败恢复后可以再次取消', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.cancelResearch
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ thread_id: 'thread-1', status: 'cancelling' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    await act(async () => {
      await result.current.cancel(1)
    })
    expect(result.current.rounds[0].status).toBe('researching')

    await act(async () => {
      await result.current.cancel(1)
    })
    act(() => {
      emitEvent?.(researchEvent('cancelled', {}, 2))
    })

    expect(mocks.cancelResearch).toHaveBeenCalledTimes(2)
    expect(result.current.rounds[0].status).toBe('cancelled')
  })

  it('Cancel 请求晚到失败时不覆盖已经到达的 completed', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    let rejectCancel: ((error: Error) => void) | null = null
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.cancelResearch.mockImplementation(() => new Promise((_resolve, reject) => {
      rejectCancel = reject
    }))
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    let cancelling: Promise<void> = Promise.resolve()
    act(() => {
      cancelling = result.current.cancel(1)
    })
    act(() => {
      emitEvent?.(researchEvent('completed', { result: '完成' }, 2))
    })
    await waitFor(() => {
      expect(result.current.rounds[0].status).toBe('completed')
    })
    await act(async () => {
      rejectCancel?.(new Error('late failure'))
      await cancelling
    })

    expect(result.current.rounds[0].status).toBe('completed')
  })

  it('Cancel 与 failed 同时发生时 failed 成为最终状态', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    let resolveCancel: ((value: { thread_id: string; status: 'cancelling' }) => void) | null = null
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.cancelResearch.mockImplementation(() => new Promise(resolve => {
      resolveCancel = resolve
    }))
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    let cancelling: Promise<void> = Promise.resolve()
    act(() => {
      cancelling = result.current.cancel(1)
    })
    act(() => {
      emitEvent?.(researchEvent('failed', { error: { message: '研究失败' } }, 2))
    })
    await waitFor(() => {
      expect(result.current.rounds[0]).toMatchObject({
        status: 'failed',
        errorMessage: '研究失败',
      })
    })
    await act(async () => {
      resolveCancel?.({ thread_id: 'thread-1', status: 'cancelling' })
      await cancelling
    })

    expect(result.current.rounds[0].status).toBe('failed')
  })

  it('SSE cancelled 比 Cancel HTTP 响应更早时仍保持 cancelled', async () => {
    let emitEvent: ((event: ResearchEvent) => void) | null = null
    let resolveCancel: ((value: { thread_id: string; status: 'cancelling' }) => void) | null = null
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.cancelResearch.mockImplementation(() => new Promise(resolve => {
      resolveCancel = resolve
    }))
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        emitEvent = onEvent
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())

    await act(async () => {
      await result.current.submit({ message: 'NVDA 怎么看' })
    })
    let cancelling: Promise<void> = Promise.resolve()
    act(() => {
      cancelling = result.current.cancel(1)
    })
    act(() => {
      emitEvent?.(researchEvent('cancelled', {}, 2))
    })
    await act(async () => {
      resolveCancel?.({ thread_id: 'thread-1', status: 'cancelling' })
      await cancelling
    })

    expect(result.current.rounds[0].status).toBe('cancelled')
  })

  it('Reset 后晚到的 Start 响应不能恢复旧 Round', async () => {
    let resolveStart: ((value: { thread_id: string; status: 'accepted' }) => void) | null = null
    mocks.startResearch.mockImplementation(() => new Promise(resolve => {
      resolveStart = resolve
    }))
    const { result } = renderHook(() => useResearchRun())
    let submitting: Promise<void> = Promise.resolve()

    act(() => {
      submitting = result.current.submit({ message: 'NVDA 怎么看' })
    })
    expect(result.current.rounds[0].status).toBe('submitting')
    act(() => {
      result.current.reset()
    })
    await act(async () => {
      resolveStart?.({ thread_id: 'thread-1', status: 'accepted' })
      await submitting
    })

    expect(result.current.rounds).toEqual([])
    expect(mocks.subscribeResearchEvents).not.toHaveBeenCalled()

    mocks.startResearch.mockReset()
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-2', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('completed', { result: '重新提交完成' }))
      },
    )
    await act(async () => {
      await result.current.submit({ message: '重新提交' })
    })

    expect(result.current.rounds).toEqual([
      expect.objectContaining({
        id: 1,
        threadId: 'thread-2',
        question: '重新提交',
        status: 'completed',
        contents: [{ type: 'text', text: '重新提交完成' }],
      }),
    ])
  })

  it('新 Submit 中止旧请求且旧响应不能修改新 Round', async () => {
    let resolveFirst: ((value: { thread_id: string; status: 'accepted' }) => void) | null = null
    mocks.startResearch
      .mockImplementationOnce(() => {
        return new Promise(resolve => {
          resolveFirst = resolve
        })
      })
      .mockResolvedValueOnce({ thread_id: 'thread-2', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void) => {
        onEvent(researchEvent('completed', { result: '第二轮完成' }))
      },
    )
    const { result } = renderHook(() => useResearchRun())
    let firstSubmitting: Promise<void> = Promise.resolve()

    act(() => {
      firstSubmitting = result.current.submit({ message: '第一轮' })
    })
    await act(async () => {
      await result.current.submit({ message: '第二轮' })
    })
    await act(async () => {
      resolveFirst?.({ thread_id: 'thread-1', status: 'accepted' })
      await firstSubmitting
    })

    const firstRequestSignal = mocks.startResearch.mock.calls[0][1] as AbortSignal
    expect(firstRequestSignal.aborted).toBe(true)
    expect(result.current.rounds[1]).toMatchObject({
      question: '第二轮',
      threadId: 'thread-2',
      status: 'completed',
      contents: [{ type: 'text', text: '第二轮完成' }],
    })
    expect(mocks.subscribeResearchEvents).toHaveBeenCalledTimes(1)
  })

  it('卸载时中止当前 SSE 网络连接和文字动画', async () => {
    let streamSignal: AbortSignal | null = null
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    mocks.startResearch.mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    mocks.subscribeResearchEvents.mockImplementation(
      async (_threadId, onEvent: (event: ResearchEvent) => void, signal: AbortSignal) => {
        streamSignal = signal
        onEvent(researchEvent('workflow_started', { execution: 'start' }))
        onEvent(researchEvent('answer_delta', { text: 'AB' }, 2))
        await Promise.resolve()
        await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }))
      },
    )
    const { result, unmount } = renderHook(() => useResearchRun())
    let submitting: Promise<void> = Promise.resolve()

    act(() => {
      submitting = result.current.submit({ message: 'NVDA 怎么看' })
    })
    await waitFor(() => {
      expect(streamSignal).not.toBeNull()
    })
    const activeSignal = mocks.subscribeResearchEvents.mock.calls[0][2] as AbortSignal
    unmount()
    await submitting

    expect(activeSignal.aborted).toBe(true)
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })
})
