import { useEffect, useRef, useState } from 'react'
import type { CreateResearchRunRequest } from '../../api/contracts'
import { createRun } from '../../api/runTransport'
import type { ResearchHistoryEntry, ResearchViewState } from './type'

export function useResearchRun(): {
  readonly state: ResearchViewState
  readonly history: readonly ResearchHistoryEntry[]
  readonly submit: (request: CreateResearchRunRequest) => Promise<void>
  readonly reset: () => void
} {
  const [state, setState] = useState<ResearchViewState>({ kind: 'idle' })
  const [history, setHistory] = useState<readonly ResearchHistoryEntry[]>([])
  const abortController = useRef(new AbortController())
  const latestRequestId = useRef(0)

  useEffect(() => {
    // 离开研究页面时，让尚未完成的响应失效。
    return () => abortController.current.abort()
  }, [])

  const submit = async (request: CreateResearchRunRequest) => {
    const message = request.message.trim()

    if (!message) {
      return
    }

    // 新一轮开始前，保留上一轮已结束的消息和回复。
    if (state.kind !== 'idle' && state.kind !== 'submitting') {
      setHistory((previous) => [...previous, state])
    }

    abortController.current.abort()
    const controller = new AbortController()
    abortController.current = controller
    const requestId = ++latestRequestId.current

    setState({ kind: 'submitting', requestId, userMessage: message })

    try {
      const response = await createRun(
        { ...request, message },
        controller.signal,
      )
      if (controller.signal.aborted) {
        return
      }
      setState({
        kind: 'received',
        requestId,
        userMessage: message,
        response,
      })
    } catch {
      if (controller.signal.aborted) {
        return
      }
      setState({
        kind: 'request_failed',
        requestId,
        userMessage: message,
        errorMessage: '暂时无法完成请求，请稍后重试。',
      })
    }
  }

  const reset = () => {
    abortController.current.abort()
    abortController.current = new AbortController()
    setState({ kind: 'idle' })
    setHistory([])
  }

  return {
    state,
    history,
    submit,
    reset,
  }
}
