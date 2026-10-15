import { useEffect, useRef, useState } from 'react'
import type { ResearchEvent, ResearchStage, StartResearchRequest } from '../../api/contracts'
import { cancelResearch, resumeResearch, startResearch } from '../../api/runTransport'
import type { ResearchRound } from './type'
import { subscribeResearchEvents } from '../../api/researchStream'
import { SSETaskQueue, TextBuffer, TextTask, type ResearchDisplayRuntime } from './sseTaskQueue'
import { useToast } from './toast'

export function useResearchRun(): {
    readonly rounds: ResearchRound[]
    readonly toastMessage: string | null
    readonly submit: (request: StartResearchRequest) => Promise<void>
    readonly reset: () => void
    readonly submitAnswer: (roundId: number, answer: string[]) => void
    readonly cancel: (roundId: number) => Promise<void>
} {
    const [rounds, setRounds] = useState<ResearchRound[]>([])

    // /api/research 和 /events 的controller
    // const researchController = useRef(new AbortController())
    const networkControllerRef = useRef(new AbortController())
    const displayControllerRef = useRef<AbortController | null>(null)
    const roundSequence = useRef(0)
    const { message: toastMessage, showToast } = useToast()


    useEffect(() => {
        // 离开研究页面时，让尚未完成的响应失效。
        return () => {
            displayControllerRef.current?.abort()
            networkControllerRef.current.abort()
        }
    }, [])

    const updateRound = (roundId: number, update: (round: ResearchRound) => ResearchRound) => {
        setRounds((pre) => pre.map((round) => round.id === roundId ? update(round): round))
    }

    const bindThreadId = (roundId: number, threadId: string) => {
        updateRound(roundId, (round) => ({ ...round, threadId }))
    }

    const appendTextChunk = (roundId: number, text: string) => {
        updateRound(roundId, (round) => {
            const contents = [...round.contents]
            const lastContent = contents[round.contents.length - 1]
            if (lastContent?.type === 'text') {
                contents[contents.length - 1] = { ...lastContent, text: lastContent.text + text }
                return { ...round, contents }
            }
            contents.push({ type: 'text', text })
            return { ...round, contents }
        })
    }

    const appendAnswerDelta = (roundId: number, runtime: ResearchDisplayRuntime, text: string) => {
        if (!text) return

        if (runtime.textBuffer === null){
            const buffer = new TextBuffer()
            runtime.textBuffer = buffer

            runtime.queue.enqueue( new TextTask(
                buffer,
                text => { appendTextChunk(roundId, text) }
            ))
        }
        runtime.textBuffer.append(text)
    }

    const sealTextSegment = ( runtime: ResearchDisplayRuntime) => {
        const buffer = runtime.textBuffer
        if (!buffer) return

        buffer.seal()

        /**
         * runtime 不再向这个
         * Buffer append 新文字。
         *
         * 但是已经在执行的 TextTask
         * 仍然持有 buffer，
         * 会继续把剩余文字打完。
         */
        runtime.textBuffer = null
    }

    const handleResearchEvent = (roundId: number, event: ResearchEvent, runtime: ResearchDisplayRuntime) => {
        switch (event.type){
            case "workflow_started":
                runtime.hasReceivedAnswerDelta = false
                const execution = event.data.execution
                updateRound(roundId, (round) => {
                    const stage = execution !== 'start' ? round.stage : null
                    const clarification = execution === 'resume' ? null : round.clarification
                    const contents = [...round.contents]
                    if (round.pendingClarificationAnswer) {
                        contents.push({ type: 'clarification_answer', text: round.pendingClarificationAnswer })
                    }
                    return {
                        ...round,
                        status: "researching",
                        errorMessage: null,
                        stage,
                        contents,
                        clarification,
                        clarificationSubmitting: false,
                        clarificationErrorMessage: null,
                        pendingClarificationAnswer: null,
                    }
                })
                return
            case "stage_changed":
                updateRound(roundId, (round) => ({ ...round, stage: event.data.stage as ResearchStage }))
                return
            case "answer_delta":
                const text = event.data.text as string
                runtime.hasReceivedAnswerDelta = true
                appendAnswerDelta(roundId, runtime, text)
                return
            case "needs_input":
                // const data = parseTargetClarification(event.data)
                sealTextSegment(runtime)
                runtime.queue.enqueue({
                    run: () => {
                    /**
                     * Workflow 即将进入暂停状态，
                     * 先展示已经收到的文字。
                     */
                    updateRound(roundId, (round) => ({
                        ...round,
                        status: "needs_input",
                        clarification: event.data as any,
                        clarificationSubmitting: false,
                        clarificationErrorMessage: null
                    }))
                }
                })
                return
            case "completed":
                const result = event.data.result as string
                if (!runtime.hasReceivedAnswerDelta && result && typeof result === 'string') {
                    appendAnswerDelta(roundId, runtime, result)
                }
                sealTextSegment(runtime)
                runtime.queue.enqueue({
                    run: () => {updateRound(roundId, (round) => ({ ...round, status: "completed", stage: null, errorMessage: null }))}
                })
                return
            case "failed":
                sealTextSegment(runtime)
                runtime.queue.enqueue({
                    run: () => {
                        sealTextSegment(runtime)
                        const errorMessage = (event?.data?.error as any)?.message || '研究任务执行失败。'
                        updateRound(roundId, (round) => ({
                            ...round,
                            status: "failed",
                            stage: null,
                            errorMessage: errorMessage }))
                    }
                })
                return
            case 'cancelled':
                runtime.controller.abort()
                runtime.textBuffer = null
                updateRound(
                    roundId,
                    (round) => ({
                        ...round,
                        status: 'cancelled',
                        stage: null,
                    }),
                )
                return
            case 'target_resolution':
                // D40.7 再处理标的确认。
                return
        }
    }

    // submit -> create round -> post -> threadId -> ssm -> handle events, 直到 terminal event
    const submit = async (request: StartResearchRequest) => {
        // 1. 校验输入
        const question = request.message.trim()
        if (!question) return

        /**
         * 停止上一轮的网络和展示。
         */
        networkControllerRef.current.abort()
        displayControllerRef.current?.abort()

        const controller = new AbortController()
        networkControllerRef.current = controller
        displayControllerRef.current = null

        // 2. 创建本地 ResearchRound
        const roundId = ++roundSequence.current
        const round: ResearchRound = {
            id: roundId,
            threadId: null,
            question,
            status: 'submitting',
            contents: [],
            errorMessage: null,
            clarification: null,
            clarificationSubmitting: false,
            clarificationErrorMessage: null,
            pendingClarificationAnswer: null,
        }
        setRounds(pre => [...pre, round])

        let thread_id = null
        // 3. 启动后端 Workflow
        try {
            const response = await startResearch(
                { message: question },
                controller.signal,
            )
            if (controller.signal.aborted) return
            thread_id = response.thread_id
        } catch {
            if (controller.signal.aborted) return
            setRounds(pre => pre.map(item => {
                if(item.id !== roundId) {
                    return item
                }
                return {
                    ...item,
                    status: 'request_failed',
                    errorMessage: '暂时无法完成请求，请稍后重试。',
                }
            }))
            return
        }

        /**
         * 后端已接受任务。
         *
         * 用本地 roundId 找到刚才创建的 Round，
         * 再绑定真正的 backend thread_id。
         */
        // 4. 把 backend threadId 绑定到本地 round
        if (thread_id) {
            bindThreadId(roundId, thread_id)
        }

        // 5. 订阅这个 workflow
        const displayController = new AbortController()
        displayControllerRef.current = displayController
        const runtime: ResearchDisplayRuntime = {
            queue: new SSETaskQueue(displayController.signal),
            textBuffer: null,
            controller: displayController,
            hasReceivedAnswerDelta: false
        }
        try {
            if (thread_id) {
                await subscribeResearchEvents(
                    thread_id,
                    (event) => handleResearchEvent(roundId, event, runtime),
                    controller.signal,
                )
            }
        } catch (error) {
            // round -> stream_failed
            if (controller.signal.aborted) {
                runtime.controller.abort()
                return
            }
            /**
             * SSE 异常意味着当前展示流不完整。
             *
             * 立即停止正在执行的 TextTask，
             * 并丢弃尚未展示的 Buffer 内容。
             */
            console.error('research stream failed', error)

            runtime.controller.abort()
            runtime.textBuffer = null
            updateRound(roundId, (round) => ({
                ...round,
                status: 'stream_failed',
                errorMessage: '研究连接已中断，请稍后重试。',
            }))
        }

        //  网络终态已经到达，但是 UI 可能仍在打字。
        try {
            await runtime.queue.flush()
        } catch (error) {
            if (runtime.controller.signal.aborted) return
            runtime.controller.abort()

            updateRound(
                roundId,
                (round) => ({  ...round, status: "display_failed", errorMessage:'研究结果展示失败，请稍后重试。' }),
            )

            console.error('research display failed', error)
        } finally {
            if (displayControllerRef.current === displayController) {
                displayControllerRef.current = null
            }
        }
    }

    const submitAnswer = async (roundId: number, answer: string[]) => {
        const round = rounds.find(r => r.id === roundId)
        if (!round || !round.threadId) return
        updateRound(roundId, (round) => ({
            ...round,
            clarificationSubmitting: true,
            clarificationErrorMessage: null,
            pendingClarificationAnswer: answer
        }))

        const signal = networkControllerRef.current.signal
        try {
            await resumeResearch({ answer: answer, thread_id: round.threadId }, signal)
            if (signal.aborted) return
            // 等 SSE workflow_started(resume) 再真正恢复 Round
        } catch {
            if (signal.aborted) return
            updateRound(roundId, (round) => ({
                ...round,
                clarificationSubmitting: false,
                clarificationErrorMessage: '补充信息提交失败，请重试。',
                pendingClarificationAnswer: null,
            }))
        }
    }

    const cancel = async (roundId: number) => {
        const round = rounds.find(r => r.id === roundId)
        if (!round?.threadId) return
        const signal = networkControllerRef.current.signal
        updateRound(roundId, (round) => ({
            ...round,
            status: 'cancelling',
            errorMessage: null,
        }))
        try {
            await cancelResearch(round.threadId, signal)
            if (signal.aborted) return
        } catch {
            if (signal.aborted) return
            updateRound(roundId, (round) => round.status === 'cancelling' ? { ...round, status: 'researching' } : round)
            // 提示取消失败
            showToast('取消研究请求失败，请稍后重试。')
        }
    }

    const reset = () => {
        networkControllerRef.current.abort()
        displayControllerRef.current?.abort()
        networkControllerRef.current = new AbortController()
        displayControllerRef.current = null
        roundSequence.current = 0
        setRounds([])
    }

    return { rounds, toastMessage, submit, reset, submitAnswer, cancel }
}
