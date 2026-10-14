import type {
  ResearchEvent,
  ResearchEventType,
} from './contracts'

import {
  RequestError,
} from './request'

import {
  stream,
  type SseEvent,
} from './stream'

const RESEARCH_EVENT_TYPES = new Set<string>([
    'workflow_started',
    'stage_changed',
    'target_resolution',
    'answer_delta',
    'needs_input',
    'completed',
    'failed',
    'cancelled',
])

const TERMINAL_EVENT_TYPES = new Set<ResearchEventType>([
    'completed',
    'failed',
    'cancelled',
])

const parseResearchEvent = (sseEvent: SseEvent, expectedThreadId: string): ResearchEvent => {
    const data = JSON.parse(sseEvent.data) as ResearchEvent

    if (
        data.thread_id !== expectedThreadId ||
        !RESEARCH_EVENT_TYPES.has(data.type)
    ) {
        throw new RequestError('invalid_response', '服务返回了无效的研究事件。')
    }

    return data
}

const isTerminalResearchEvent = (event: ResearchEvent): boolean => {
    return TERMINAL_EVENT_TYPES.has(event.type)
}


export async function subscribeResearchEvents(threadId: string, cb: (event: ResearchEvent) => void, signal: AbortSignal) {
    const onEvent = async (sseEvent: SseEvent) => {
        const event = parseResearchEvent(sseEvent, threadId)
        if (signal.aborted) return
        await cb(event)
        return isTerminalResearchEvent(event) ? false : true
    }
    return stream(`/api/research/${threadId}/events`, {
        onEvent,
        signal,
        connectionKey: `research:${threadId}`
    })
}
