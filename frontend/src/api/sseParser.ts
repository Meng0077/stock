import { RequestError } from './requestErrors'

/** SSE 信封；data 保留原始字符串，不在传输层解析业务 JSON。 */
export interface SseEvent {
  readonly event: string
  readonly data: string
  /** 继承上一条 id；空 id 表示重置游标。 */
  readonly id: string
}

export type SseFrame =
  | { readonly kind: 'event'; readonly value: SseEvent }
  | { readonly kind: 'cursor'; readonly id: string }
  | { readonly kind: 'retry'; readonly milliseconds: number }

/**
 * 增量按行解析，不把网络 chunk 当事件边界。
 * 支持 CR/LF/CRLF、多行 data、注释、id 和 retry；EOF 不补发残缺事件。
 */
export function createSseParser(initialId: string, maxBufferChars: number): {
  readonly feed: (text: string) => readonly SseFrame[]
} {
  let line = ''
  let skipLf = false
  let data: string[] = []
  let event = ''
  let id = initialId
  let idChanged = false
  let bufferedChars = 0

  const processLine = (frames: SseFrame[]) => {
    if (line === '') {
      if (data.length > 0) {
        frames.push({ kind: 'event', value: { event: event || 'message', data: data.join('\n'), id } })
      } else if (idChanged) {
        frames.push({ kind: 'cursor', id })
      }
      data = []
      event = ''
      idChanged = false
      bufferedChars = 0
      return
    }
    if (line.startsWith(':')) return
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const rawValue = colon === -1 ? '' : line.slice(colon + 1)
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
    switch (field) {
      case 'data':
        data.push(value)
        bufferedChars += value.length + 1
        break
      case 'event':
        event = value
        break
      case 'id':
        if (!value.includes('\0')) {
          id = value
          idChanged = true
        }
        break
      case 'retry': {
        const milliseconds = Number(value)
        if (/^\d+$/.test(value) && Number.isSafeInteger(milliseconds) && milliseconds <= 2_147_483_647) {
          frames.push({ kind: 'retry', milliseconds })
        }
        break
      }
    }
  }

  return {
    feed(text) {
      const frames: SseFrame[] = []
      for (const char of text) {
        if (skipLf) {
          skipLf = false
          if (char === '\n') continue
        }
        if (char === '\r' || char === '\n') {
          processLine(frames)
          line = ''
          skipLf = char === '\r'
        } else {
          line += char
        }
        if (line.length + bufferedChars + event.length + id.length > maxBufferChars) {
          throw new RequestError('invalid_response', '事件内容超出允许的大小。')
        }
      }
      return frames
    },
  }
}
