import {
  RequestError,
  abortedError,
  httpErrorMessage,
  isRequestAborted,
  networkError,
} from './requestErrors'
import { isRecoverableError, linkedController, retryWaitMs, waitForRetry } from './requestControl'

export interface RequestPolicy {
  /** 单次 HTTP 尝试的超时，包含正文读取；0 表示关闭。 */
  readonly timeout?: number
  /** GET/HEAD 的最大额外尝试次数，默认 2；写操作忽略此配置。 */
  readonly retries?: number
  /** 指数退避的基础毫秒数，默认 500。 */
  readonly retryDelay?: number
}

/** 每次尝试都新建 Controller；外部取消和超时都转为 abort。 */
async function attemptRequest(
  url: string | URL,
  options: RequestInit,
  requestSignal: AbortSignal,
  timeout: number,
): Promise<Response> {
  const { controller, dispose } = linkedController(requestSignal)

  const timer = timeout > 0 ? setTimeout(() => {
    controller.abort(new RequestError('timeout', '请求超时，请稍后重试。'))
  }, timeout) : undefined

  try {
    if (controller.signal.aborted) throw abortedError()
    const response = await fetch(url, { ...options, signal: controller.signal })
    if (response.status === 0) throw networkError()

    // 完整读取副本，超时覆盖正文下载；保留原 Response 给 API/共享层读取。
    // 此请求层用于有限响应，不用于 SSE 或无限流。
    await response.clone().arrayBuffer()
    if (controller.signal.aborted) throw controller.signal.reason
    if (!response.ok) {
      throw new RequestError('http', httpErrorMessage(response.status), response)
    }
    return response
  } catch (error) {
    if (requestSignal.aborted) throw abortedError()
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason
      if (reason instanceof RequestError && reason.kind === 'timeout') throw reason
      throw abortedError()
    }
    if (error instanceof RequestError) throw error
    if (isRequestAborted(error)) throw abortedError()
    throw networkError()
  } finally {
    clearTimeout(timer)
    dispose()
  }
}

/** 请求级 Controller 覆盖所有尝试与退避；主动取消后绝不重试。 */
export async function performRequest(
  url: string | URL,
  options: RequestInit,
  policy: RequestPolicy,
): Promise<Response> {
  const { timeout = 10_000, retries = 2, retryDelay = 500 } = policy
  if (
    !Number.isFinite(timeout) || timeout < 0 || timeout > 2_147_483_647 ||
    !Number.isInteger(retries) || retries < 0 || retries > 5 ||
    !Number.isFinite(retryDelay) || retryDelay < 0
  ) {
    throw new RangeError('timeout/retryDelay 必须为非负有限数，retries 必须为 0～5 的整数。')
  }

  const { controller, dispose } = linkedController(options.signal)

  const method = (options.method ?? 'GET').toUpperCase()
  const maxRetries = method === 'GET' || method === 'HEAD' ? retries : 0

  try {
    for (let attempt = 0; ; attempt += 1) {
      if (controller.signal.aborted) throw abortedError()
      try {
        return await attemptRequest(url, options, controller.signal, timeout)
      } catch (error) {
        if (controller.signal.aborted) throw abortedError()
        if (attempt >= maxRetries || !isRecoverableError(error)) throw error
        // 单次尝试的 timer/listener 已清理，再开始退避。
        await waitForRetry(retryWaitMs(error, attempt, retryDelay), controller.signal)
      }
    }
  } finally {
    dispose()
  }
}
