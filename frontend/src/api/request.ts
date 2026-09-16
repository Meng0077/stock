import { RequestError, abortedError, isRequestAborted, networkError } from './requestErrors'
import { performRequest, type RequestPolicy } from './requestLifecycle'

export { RequestError, isRequestAborted } from './requestErrors'
export type { RequestErrorKind } from './requestErrors'

export interface RequestOptions extends RequestInit, RequestPolicy {
  /** 只对 GET/HEAD 生效；强制刷新时设为 false，SSE 使用 stream 入口。 */
  readonly dedupe?: boolean
  /** 从第一次发起时计时，不因后续命中而延长。 */
  readonly dedupeTtlMs?: 1000 | 2000
}

interface SharedRequest {
  readonly controller: AbortController
  readonly promise: Promise<Response>
  readonly expiresAt: number
  subscribers: number
  settled: boolean
}

const sharedRequests = new Map<string, SharedRequest>()

function forgetSharedRequest(key: string, entry: SharedRequest): void {
  // 旧请求结束时不能移除同 key 的新一轮请求。
  if (sharedRequests.get(key) === entry) {
    sharedRequests.delete(key)
  }
}

function subscribeToRequest(
  key: string,
  entry: SharedRequest,
  signal?: AbortSignal | null,
): Promise<Response> {
  entry.subscribers += 1

  return new Promise((resolve, reject) => {
    let finished = false

    const release = () => {
      finished = true
      signal?.removeEventListener('abort', onAbort)
      entry.subscribers -= 1
      if (entry.subscribers === 0 && !entry.settled) {
        forgetSharedRequest(key, entry)
        entry.controller.abort()
      }
    }

    const onAbort = () => {
      if (!finished) {
        release()
        reject(abortedError())
      }
    }

    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) {
      onAbort()
    }

    entry.promise.then(
      (response) => {
        if (finished) return
        release()
        try {
          // Response 的正文只能读一次，各调用方必须拿到自己的副本。
          resolve(response.clone())
        } catch {
          reject(new RequestError('invalid_response', '服务返回了无法读取的响应。'))
        }
      },
      (error: unknown) => {
        if (finished) return
        release()
        try {
          if (error instanceof RequestError && error.response) {
            reject(new RequestError(error.kind, error.message, error.response.clone()))
          } else {
            reject(error)
          }
        } catch {
          reject(new RequestError('invalid_response', '服务返回了无法读取的响应。'))
        }
      },
    )
  })
}

/**
 * GET/HEAD 在 1 或 2 秒内共享第一次请求；其他方法永远不共享。
 * 匹配 URL、方法、请求头及其他 fetch 选项，不跨权限/参数复用。
 * 请求层会完整读取正文，不适用于 SSE/大文件流式接口。
 */
export async function request(
  url: string | URL,
  options: RequestOptions = {},
): Promise<Response> {
  if (options.signal?.aborted) {
    throw abortedError()
  }

  const {
    dedupe = true,
    dedupeTtlMs = 2000,
    timeout = 10_000,
    retries = 2,
    retryDelay = 500,
    signal,
    method = 'GET',
    headers,
    ...rest
  } = options
  const normalizedMethod = method.toUpperCase()
  const fetchOptions = { ...rest, signal, method: normalizedMethod, headers }
  const policy = { timeout, retries, retryDelay }

  if (
    !dedupe ||
    (normalizedMethod !== 'GET' && normalizedMethod !== 'HEAD') ||
    rest.body != null ||
    rest.cache === 'no-store' ||
    rest.cache === 'no-cache'
  ) {
    return performRequest(url, fetchOptions, policy)
  }

  const requestHeaders: [string, string][] = []
  new Headers(headers).forEach((value, name) => requestHeaders.push([name, value]))
  const key = JSON.stringify([
    String(url),
    normalizedMethod,
    requestHeaders.sort(([a], [b]) => a.localeCompare(b)),
    Object.entries(rest).sort(([a], [b]) => a.localeCompare(b)),
    dedupeTtlMs,
    policy,
  ])

  let entry = sharedRequests.get(key)
  if (!entry || entry.expiresAt <= Date.now()) {
    const controller = new AbortController()
    const newEntry: SharedRequest = {
      controller,
      expiresAt: Date.now() + dedupeTtlMs,
      subscribers: 0,
      settled: false,
      promise: performRequest(url, { ...fetchOptions, signal: controller.signal }, policy)
        .then((response) => {
          newEntry.settled = true
          if (/\bno-(?:store|cache)\b/i.test(response.headers.get('Cache-Control') ?? '')) {
            forgetSharedRequest(key, newEntry)
          }
          return response
        })
        .catch((error: unknown) => {
          newEntry.settled = true
          forgetSharedRequest(key, newEntry)
          throw error
        }),
    }
    entry = newEntry
    sharedRequests.set(key, newEntry)
    setTimeout(() => forgetSharedRequest(key, newEntry), dedupeTtlMs)
  }

  return subscribeToRequest(key, entry, signal)
}

/**
 * JSON 入口：成功返回 unknown，由具体 API 校验和处理业务结果。
 * 204/205 返回 null；错误 JSON、读取中断及取消统一归类。
 * JSON 请求体仍由调用方序列化，并声明 Content-Type。
 */
export async function requestJson(
  url: string | URL,
  options: RequestOptions = {},
): Promise<unknown> {
  const headers = new Headers(options.headers)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  const response = await request(url, { ...options, headers })

  if (options.signal?.aborted) {
    throw abortedError()
  }
  if (response.status === 204 || response.status === 205) {
    return null
  }

  try {
    const body: unknown = await response.json()
    if (options.signal?.aborted) {
      throw abortedError()
    }
    return body
  } catch (error) {
    if (options.signal?.aborted || isRequestAborted(error)) {
      throw abortedError()
    }
    if (error instanceof SyntaxError) {
      throw new RequestError('invalid_response', '服务返回了无法解析的响应。')
    }
    throw networkError()
  }
}
