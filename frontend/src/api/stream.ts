import {
  RequestError,
  abortedError,
  httpErrorMessage,
  isRequestAborted,
  networkError,
} from './requestErrors'
import {
  isRecoverableError,
  linkedController,
  retryWaitMs,
  signalError,
  waitForRetry,
  withSignal,
} from './requestControl'
import { createSseParser, type SseEvent } from './sseParser'

export type { SseEvent } from './sseParser'

export interface StreamOptions extends RequestInit {
  /** 原始事件按顺序交付；返回 false 表示业务终态，正常关闭且不重连。 */
  readonly onEvent: (event: SseEvent) => void | boolean | Promise<void | boolean>
  readonly onOpen?: (info: { readonly url: string; readonly headers: Headers }) => void | Promise<void>
  /** 只覆盖建立连接，默认 10 秒；0 关闭。 */
  readonly connectTimeout?: number
  /** 等待网络数据/注释心跳的超时，默认 30 秒；0 关闭。 */
  readonly idleTimeout?: number
  /** 默认 true，但只有 GET 允许自动重连。 */
  readonly reconnect?: boolean
  /** 整个生命周期最多额外重连次数，默认 3。 */
  readonly maxReconnects?: number
  readonly reconnectDelay?: number
  readonly maxReconnectDelay?: number
  readonly lastEventId?: string
  /** 默认一百万字符，限制单行/未完成事件的内存。 */
  readonly maxBufferChars?: number
  /** 显式替换同业务 key 的 GET 连接；不按 URL 自动取消，不作用于 POST。 */
  readonly connectionKey?: string
}

interface StreamCursor {
  id: string
  retryDelay: number | undefined
}

const connections = new Map<string, AbortController>()

async function callHandler<T>(task: () => T | Promise<T>, signal: AbortSignal): Promise<T> {
  try {
    return await withSignal(Promise.resolve().then(() => {
      if (signal.aborted) throw signalError(signal)
      return task()
    }), signal)
  } catch {
    if (signal.aborted) throw signalError(signal)
    // 业务回调抛错不应被误当网络故障并重连。
    throw new RequestError('handler', '事件处理失败，连接已停止。')
  }
}

async function connectOnce(
  url: string | URL,
  options: RequestInit,
  requestSignal: AbortSignal,
  cursor: StreamCursor,
  config: Pick<StreamOptions, 'onEvent' | 'onOpen'> & {
    readonly connectTimeout: number
    readonly idleTimeout: number
    readonly maxBufferChars: number
  },
): Promise<void> {
  const { controller, dispose } = linkedController(requestSignal)
  let connectTimer: ReturnType<typeof setTimeout> | undefined
  let idleTimer: ReturnType<typeof setTimeout> | undefined
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  let response: Response | undefined

  const armIdleTimer = () => {
    clearTimeout(idleTimer)
    if (config.idleTimeout > 0) {
      idleTimer = setTimeout(() => {
        controller.abort(new RequestError('timeout', '事件连接长时间未收到数据。'))
      }, config.idleTimeout)
    }
  }

  if (config.connectTimeout > 0) {
    connectTimer = setTimeout(() => {
      controller.abort(new RequestError('timeout', '事件连接建立超时。'))
    }, config.connectTimeout)
  }

  try {
    if (controller.signal.aborted) throw signalError(controller.signal)
    const headers = new Headers(options.headers)
    headers.set('Accept', 'text/event-stream')
    headers.delete('Last-Event-ID')
    if (cursor.id) {
      // WHATWG Last-Event-ID 使用 UTF-8 字节；Headers 要求 ByteString。
      const bytes = new TextEncoder().encode(cursor.id)
      headers.set('Last-Event-ID', Array.from(bytes, (byte) => String.fromCharCode(byte)).join(''))
    }
    response = await withSignal(fetch(url, {
      ...options, headers, cache: 'no-store', signal: controller.signal,
    }), controller.signal)
    if (response.status === 0) throw networkError()
    if (response.status === 204) return
    if (!response.ok) {
      // 保留可独立读取的 HTTP 错误正文，交由具体 API 决定业务处理。
      const body = await withSignal(response.arrayBuffer(), controller.signal)
      const errorResponse = new Response(body, {
        status: response.status, statusText: response.statusText, headers: response.headers,
      })
      throw new RequestError('http', httpErrorMessage(response.status), errorResponse)
    }
    const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()
    if (response.status !== 200 || contentType !== 'text/event-stream' || !response.body) {
      throw new RequestError('invalid_response', '服务未返回有效的事件流。')
    }
    clearTimeout(connectTimer)
    if (config.onOpen) {
      const info = { url: response.url, headers: new Headers(response.headers) }
      await callHandler(() => config.onOpen?.(info), controller.signal)
    }

    reader = response.body.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser(cursor.id, config.maxBufferChars)
    armIdleTimer()

    while (true) {
      const chunk = await withSignal(reader.read(), controller.signal)
      if (chunk.done) {
        // EOF 不是业务终态；未以空行结束的事件不会被交付或推进游标。
        throw new RequestError('network', '事件连接意外断开。')
      }
      if (chunk.value.length === 0) continue
      clearTimeout(idleTimer)
      const frames = parser.feed(decoder.decode(chunk.value, { stream: true }))
      for (const frame of frames) {
        if (controller.signal.aborted) throw signalError(controller.signal)
        if (frame.kind === 'retry') cursor.retryDelay = frame.milliseconds
        else if (frame.kind === 'cursor') cursor.id = frame.id
        else {
          const keepGoing = await callHandler(() => config.onEvent(frame.value), controller.signal)
          // 回调成功后才确认游标，避免尚未应用的事件在重连时被跳过。
          cursor.id = frame.value.id
          if (keepGoing === false) return
        }
      }
      // 业务回调期间暂停空闲计时，避免把消费端背压误判成断线。
      armIdleTimer()
    }
  } catch (error) {
    if (requestSignal.aborted) throw abortedError()
    if (controller.signal.aborted) throw signalError(controller.signal)
    if (error instanceof RequestError) throw error
    if (isRequestAborted(error)) throw abortedError()
    throw networkError()
  } finally {
    clearTimeout(connectTimer)
    clearTimeout(idleTimer)
    controller.abort(abortedError())
    // 不等待可能悬挂的底层 cancel，清理过程不能阻塞新一轮连接。
    if (reader) {
      void reader.cancel().catch(() => undefined)
      reader.releaseLock()
    } else if (response?.body && !response.body.locked) {
      void response.body.cancel().catch(() => undefined)
    }
    dispose()
  }
}

/**
 * fetch SSE 入口。完成：onEvent 返回 false 或 HTTP 204。
 * 取消/终止故障：抛 RequestError。GET 可有限重连；写操作只连接一次。
 * 不创建任务、不解析业务 JSON、不保证 exactly-once，也不取消后端任务。
 */
export async function stream(url: string | URL, options: StreamOptions): Promise<void> {
  const {
    onEvent, onOpen, connectTimeout = 10_000, idleTimeout = 30_000,
    reconnect = true, maxReconnects = 3, reconnectDelay = 1000,
    maxReconnectDelay = 30_000, maxBufferChars = 1_000_000,
    lastEventId, connectionKey, signal, method = 'GET', ...rest
  } = options
  const timings = [connectTimeout, idleTimeout, reconnectDelay, maxReconnectDelay]
  if (
    timings.some((value) => !Number.isFinite(value) || value < 0 || value > 2_147_483_647) ||
    !Number.isInteger(maxReconnects) || maxReconnects < 0 ||
    !Number.isSafeInteger(maxBufferChars) || maxBufferChars <= 0 ||
    typeof onEvent !== 'function'
  ) {
    throw new RangeError('事件流配置无效，请检查超时、重连次数和缓冲限制。')
  }
  const cursor: StreamCursor = {
    id: lastEventId ?? new Headers(rest.headers).get('Last-Event-ID') ?? '',
    retryDelay: undefined,
  }
  if (/[\0\r\n]/.test(cursor.id)) throw new RangeError('事件游标不能包含空字符或换行。')
  if (signal?.aborted) throw abortedError()

  const normalizedMethod = method.toUpperCase()
  const { controller, dispose } = linkedController(signal)
  const key = normalizedMethod === 'GET' ? connectionKey : undefined
  if (key !== undefined) {
    connections.get(key)?.abort(abortedError())
    connections.set(key, controller)
  }

  try {
    for (let attempt = 0; ; attempt += 1) {
      if (controller.signal.aborted) throw abortedError()
      try {
        await connectOnce(url, { ...rest, method: normalizedMethod }, controller.signal, cursor, {
          onEvent, onOpen, connectTimeout, idleTimeout, maxBufferChars,
        })
        if (controller.signal.aborted) throw abortedError()
        return
      } catch (error) {
        if (controller.signal.aborted) throw abortedError()
        if (!reconnect || normalizedMethod !== 'GET' || attempt >= maxReconnects || !isRecoverableError(error)) {
          throw error
        }
        const backoff = retryWaitMs(error, attempt, reconnectDelay, maxReconnectDelay)
        const delay = Math.max(backoff, cursor.retryDelay ?? 0)
        await waitForRetry(delay, controller.signal)
      }
    }
  } finally {
    dispose()
    if (key !== undefined && connections.get(key) === controller) connections.delete(key)
  }
}
