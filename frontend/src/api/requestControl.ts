import { RequestError, abortedError } from './requestErrors'

/** 将生命周期取消转发给当前 Controller，并提供监听器清理。 */
export function linkedController(signal?: AbortSignal | null): {
  readonly controller: AbortController
  readonly dispose: () => void
} {
  const controller = new AbortController()
  const onAbort = () => controller.abort(abortedError())
  signal?.addEventListener('abort', onAbort, { once: true })
  if (signal?.aborted) onAbort()
  return {
    controller,
    dispose: () => signal?.removeEventListener('abort', onAbort),
  }
}

/** 单次超时保留 timeout 分类；其他取消归为 aborted。 */
export function signalError(signal: AbortSignal): RequestError {
  const reason: unknown = signal.reason
  return reason instanceof RequestError ? reason : abortedError()
}

/** 等待任务时也响应取消；晚到的结果/异常不会重新进入调用方。 */
export function withSignal<T>(task: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener('abort', onAbort)
      reject(signalError(signal))
    }
    signal.addEventListener('abort', onAbort, { once: true })
    if (signal.aborted) onAbort()
    task.then(
      (value) => {
        signal.removeEventListener('abort', onAbort)
        if (signal.aborted) reject(signalError(signal))
        else resolve(value)
      },
      (error: unknown) => {
        signal.removeEventListener('abort', onAbort)
        reject(signal.aborted ? signalError(signal) : error)
      },
    )
  })
}

/** 可取消的退避等待，结束和取消都会清理 timer/listener。 */
export function waitForRetry(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signalError(signal))
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
    }
    const onAbort = () => {
      cleanup()
      reject(signalError(signal))
    }
    const timer = setTimeout(() => {
      cleanup()
      resolve()
    }, Math.min(ms, 2_147_483_647))
    signal.addEventListener('abort', onAbort, { once: true })
    if (signal.aborted) onAbort()
  })
}

export function isRecoverableError(error: unknown): boolean {
  if (!(error instanceof RequestError)) return false
  if (error.kind === 'network' || error.kind === 'timeout') return true
  return error.kind === 'http' && (
    error.status === 408 || error.status === 429 || (error.status ?? 0) >= 500
  )
}

/** 指数部分有上限，服务端 Retry-After 仍作为最小等待时间。 */
export function retryWaitMs(
  error: unknown,
  attempt: number,
  baseDelay: number,
  maxDelay = 30_000,
): number {
  const backoff = Math.min(baseDelay * 2 ** attempt, maxDelay) + Math.random() * 200
  const retryAfter = error instanceof RequestError
    ? error.response?.headers.get('Retry-After')
    : null
  if (!retryAfter) return backoff
  const seconds = Number(retryAfter)
  const serverDelay = Number.isFinite(seconds)
    ? seconds * 1000
    : Date.parse(retryAfter) - Date.now()
  return Number.isFinite(serverDelay) ? Math.max(backoff, serverDelay) : backoff
}
