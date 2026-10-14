export interface SSETask {
    run( signal: AbortSignal ): void | Promise<void>
}


export class SSETaskQueue {
    private tail: Promise<void> = Promise.resolve()

    private failure: unknown = null

    private readonly signal: AbortSignal

    constructor(signal: AbortSignal){
        this.signal = signal
    }

    enqueue(task: SSETask): void{
        this.tail = this.tail.then(async () => {
            if (this.signal.aborted) {
                return
            }
            try {
                await task.run(this.signal)
            } catch (error) {
                this.failure = error
            }
        })
    }


    async flush(): Promise<void> {
        await this.tail

        if (this.failure !== null){
            throw this.failure
        }
    }
}

type CommitText = (text: string) => void

export class TextBuffer {
    /**
     * 已经从 SSE 收到，
     * 但尚未显示到 UI 的文字。
     */
    private pendingText = ''

    /**
     * true 表示这一段 Text
     * 后面不会再追加新字符。
     */
    private sealed = false

    /**
     * TextTask 当前可能因为 Buffer 为空
     * 而等待新的 delta。
     */
    private waiter: (() => void) | null = null

    append(text: string) {
        if (!text || this.sealed) return
        this.pendingText += text
        this.wake()
    }

    /**
     * 当前文字段结束。
     *
     * Card / needs_input /
     * terminal 到达时调用。
     */
    seal(): void {
        if (this.sealed) return

        this.sealed = true

        this.wake()
    }

    /**
     * TextTask 的真正消费循环。
     *
     * Promise 只有在：
     *
     * 1. Buffer 已 seal
     * 2. pendingText 已全部显示
     *
     * 后才 resolve。
     */
    async consume(commit: CommitText, signal: AbortSignal): Promise<void> {
        while (!signal.aborted) {
            if (this.pendingText){
                const character = this.takeNextCharacter()
                if (character) commit(character)
                await nextAnimationFrame(signal)
                continue
            }
            /**
             * 没有剩余文字，
             * 并且这段已经结束。
             */
            if (this.sealed) return
            /**
            * 当前只是暂时没有新 delta。
            *
            * TextTask 不能结束，
            * 否则后面的 Card 可能提前执行。
            */
            await this.startWaiting(signal)
        }
    }

    private takeNextCharacter(): string {
        const codePoint = this.pendingText.codePointAt(0)
        if (codePoint === undefined) {
            return ''
        }

        const char = String.fromCodePoint(codePoint)
        this.pendingText = this.pendingText.slice(char.length)
        return char
    }


    private startWaiting(signal: AbortSignal): Promise<void> {
        if (signal.aborted) return Promise.resolve()

        return new Promise(resolve => {
            let finished = false
            const finishWaiting = () => {
                if (finished) return
                finished = true
                signal.removeEventListener('abort', finishWaiting)

                if (this.waiter === finishWaiting) this.waiter = null
                resolve()
            }

            this.waiter = finishWaiting

            signal.addEventListener('abort', finishWaiting)
        })
    }

    private wake(): void {
        const waiter = this.waiter
        this.waiter = null
        waiter?.()
    }

}

export class TextTask implements SSETask {
    private readonly buffer: TextBuffer
    private readonly commit: CommitText
    constructor(buffer: TextBuffer, commit: CommitText){
        this.buffer = buffer
        this.commit = commit
    }

    run(signal: AbortSignal): Promise<void> {
        return this.buffer.consume(this.commit, signal)
    }
}

// 等待下一帧
function nextAnimationFrame( signal: AbortSignal): Promise<void> {
    if (signal.aborted) return Promise.resolve()

    return new Promise(resolve => {

        let finished = false

        const finish = () => {
            if (finished) return
            finished = true
            signal.removeEventListener('abort', onAbort)

            resolve()
        }

        const frameId = requestAnimationFrame(finish)
        const onAbort = () => {
            cancelAnimationFrame(frameId)
            finish()
        }

        signal.addEventListener('abort', onAbort, {once: true})
    })
}

export interface ResearchDisplayRuntime {
    readonly queue:
        SSETaskQueue

    textBuffer:
        TextBuffer | null

    readonly controller: AbortController

    hasReceivedAnswerDelta: boolean
}
