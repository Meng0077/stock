import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResearchEvent, ResearchEventType } from './contracts'
import { subscribeResearchEvents } from './researchStream'


const encoder = new TextEncoder()


function researchEventFrame(
  eventId: number,
  type: ResearchEventType,
  data: Record<string, unknown> = {},
): string {
  return [
    `id: ${eventId}`,
    `event: ${type}`,
    `data: ${JSON.stringify({
      thread_id: 'thread-1',
      event_id: eventId,
      type,
      data,
      created_at: '2026-10-14T12:00:00Z',
    })}`,
    '',
    '',
  ].join('\n')
}


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


async function advanceReconnect(subscription: Promise<void>): Promise<void> {
  await vi.advanceTimersByTimeAsync(1200)
  await subscription
}


afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})


describe('Research SSE reconnect', () => {
  it.each(['failed', 'cancelled'] as const)('断线后 replay %s 终态', async (terminalType) => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(eventStream(researchEventFrame(1, 'answer_delta', { text: '已收到' })))
      .mockResolvedValueOnce(eventStream(researchEventFrame(2, terminalType)))
    vi.stubGlobal('fetch', fetchMock)
    const received: ResearchEvent[] = []

    const subscription = subscribeResearchEvents(
      'thread-1',
      event => received.push(event),
      new AbortController().signal,
    )
    await advanceReconnect(subscription)

    expect(received.map(event => event.type)).toEqual(['answer_delta', terminalType])
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Last-Event-ID')).toBe('1')
  })

  it('needs_input 前断线后 replay 一次 clarification 并继续到 completed', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(eventStream(researchEventFrame(1, 'workflow_started', { execution: 'start' })))
      .mockResolvedValueOnce(eventStream(
        researchEventFrame(2, 'needs_input', {
          type: 'target_clarification',
          message: '请选择股票。',
          ambiguous_targets: [],
          unresolved_mentions: ['Google'],
        }) + researchEventFrame(3, 'completed', { result: '完成' }),
      ))
    vi.stubGlobal('fetch', fetchMock)
    const received: ResearchEvent[] = []

    const subscription = subscribeResearchEvents(
      'thread-1',
      event => received.push(event),
      new AbortController().signal,
    )
    await advanceReconnect(subscription)

    expect(received.map(event => event.type)).toEqual([
      'workflow_started',
      'needs_input',
      'completed',
    ])
  })

  it('needs_input 已消费后重连不会重复 clarification', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(eventStream(researchEventFrame(1, 'needs_input', {
        type: 'target_clarification',
        message: '请选择股票。',
        ambiguous_targets: [],
        unresolved_mentions: ['Google'],
      })))
      .mockResolvedValueOnce(eventStream(researchEventFrame(2, 'completed', { result: '完成' })))
    vi.stubGlobal('fetch', fetchMock)
    const received: ResearchEvent[] = []

    const subscription = subscribeResearchEvents(
      'thread-1',
      event => received.push(event),
      new AbortController().signal,
    )
    await advanceReconnect(subscription)

    expect(received.map(event => event.type)).toEqual(['needs_input', 'completed'])
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Last-Event-ID')).toBe('1')
  })
})
