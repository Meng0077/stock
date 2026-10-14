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
 * HTTP 底层入口。
 *
 * 负责：
 * - timeout
 * - retry
 * - abort
 * - GET / HEAD dedupe
 * - HTTP error
 *
 * 返回原始 Response，
 * 不处理业务 JSON。
 */
export async function requestResponse(
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
    const fetchOptions: RequestInit = {
        ...rest,
        signal,
        method: normalizedMethod,
        headers,
    }

    const policy: RequestPolicy = {
        timeout,
        retries,
        retryDelay,
    }

    /**
     * 以下情况不共享请求：
     *
     * - 显式关闭 dedupe
     * - 非 GET / HEAD
     * - 带 body
     * - no-store / no-cache
     */
    if (!dedupe || (normalizedMethod !== 'GET' && normalizedMethod !== 'HEAD') || rest.body || rest.cache === 'no-store' || rest.cache === 'no-cache') {
        return performRequest(url, fetchOptions, policy)
    }

    const requestHeader: [string, string][] = []

    new Headers(headers).forEach((val, key) => {
        requestHeader.push([key, val])
    })
    const key = JSON.stringify([
        String(url),
        normalizedMethod,
        requestHeader.sort((pre, next) => pre[0].localeCompare(next[0])),
        Object.entries(rest).sort((pre, next) => pre[0].localeCompare(next[0])),
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
            promise: performRequest(
                url,
                { ...fetchOptions, signal: controller.signal },
                policy,
            )
            .then((response) => {
                newEntry.settled = true
                if (/\bno-(?:store|cache)\b/i.test(response.headers.get('Cache-Control',) ?? '')){
                    forgetSharedRequest(key, newEntry)
                }
                return response
            }).catch(( error: unknown) => {
                newEntry.settled = true
                forgetSharedRequest(key, newEntry)
                throw error
            })
        }
        entry = newEntry
        sharedRequests.set(key, newEntry)

        setTimeout(() => {
            forgetSharedRequest(key, newEntry)
        }, dedupeTtlMs)
    }

    return subscribeToRequest(key, entry, signal)
}

/**
 * 普通 API 的统一入口。
 *
 * 默认约定服务端返回 JSON。
 *
 * 负责：
 * - 调用底层 HTTP request
 * - Accept: application/json
 * - 204 / 205
 * - JSON response 解析
 * - JSON 解析异常
 *
 * SSE 不走这里，继续使用 stream()。
 */
export async function request<T = unknown>(
    url: string | URL,
    options: RequestOptions = {}
): Promise<T> {
    const headers = new Headers(options.headers)
    headers.set("Accept", "application/json")

    const response = await requestResponse(
        url,
        {
            ...options,
            headers
        }
    )

    if (options?.signal?.aborted) {
        throw abortedError()
    }

    if (response.status === 204 || response.status === 205) {
        return null as T
    }
    try {
        const data = await response.json() as T
        if(options?.signal?.aborted){
            throw abortedError()
        }
        return data

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

// get
export function get<T>(
  url: string | URL,
  options: Omit<RequestOptions,'method' | 'body'> = {},
): Promise<T> {
    return request(
        url,
        {
            ...options,
            method: 'GET',
        },
    )
}

// post
export function post<TResponse,TBody = unknown>(
    url: string | URL,
    body: TBody,
    options: Omit<RequestOptions,'method' | 'body'> = {},
): Promise<TResponse> {
    const headers = new Headers(options.headers)
    headers.set("Content-Type", "application/json")
    headers.set("Accept", "application/json")

    return request<TResponse>(
        url,
        {
            ...options,
            method: 'POST',
            headers,
            body: JSON.stringify(body),
        },
    )
}
