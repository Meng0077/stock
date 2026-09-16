export type RequestErrorKind =
  | 'aborted'
  | 'timeout'
  | 'network'
  | 'http'
  | 'invalid_response'
  | 'handler'

/** 传输层错误；message 是安全提示，response 仅供具体 API 解析。 */
export class RequestError extends Error {
  readonly kind: RequestErrorKind
  readonly status?: number
  readonly response?: Response

  constructor(kind: RequestErrorKind, message: string, response?: Response) {
    super(message)
    this.name = 'RequestError'
    this.kind = kind
    this.status = response?.status
    this.response = response
  }
}

/** 超时与主动取消不同：超时可以重试，主动取消必须停止。 */
export function isRequestAborted(error: unknown): boolean {
  return (
    (error instanceof RequestError && error.kind === 'aborted') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

export function abortedError(): RequestError {
  return new RequestError('aborted', '请求已取消。')
}

export function networkError(): RequestError {
  // 浏览器无法可靠区分 CORS、断网和 DNS 故障。
  return new RequestError('network', '无法连接服务，请检查网络或稍后重试。')
}

export function httpErrorMessage(status: number): string {
  switch (status) {
    case 400:
    case 422:
      return '请求未被接受，请检查提交内容。'
    case 401:
      return '身份验证失败，请重新登录后重试。'
    case 403:
      return '没有访问该资源的权限。'
    case 404:
      return '请求的资源或接口不存在。'
    case 405:
      return '接口不支持当前请求方式。'
    case 408:
    case 504:
      return '服务响应超时，请稍后重试。'
    case 409:
      return '请求与当前资源状态冲突，请刷新后重试。'
    case 413:
      return '提交内容过大，请缩减后重试。'
    case 415:
      return '接口不支持提交内容的格式。'
    case 429:
      return '请求过于频繁，请稍后重试。'
    default:
      return status >= 500
        ? '服务暂时不可用，请稍后重试。'
        : '请求未能完成，请稍后重试。'
  }
}
