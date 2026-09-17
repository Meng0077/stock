import type { CreateResearchRunRequest, RunResponse } from './contracts'
import { requestJson } from './request'

export type CreateRun = (
  request: CreateResearchRunRequest,
  signal?: AbortSignal,
) => Promise<RunResponse>

export interface RunTransport {
  readonly createRun: CreateRun
}

export async function createRun(
  request: CreateResearchRunRequest,
  signal?: AbortSignal,
): Promise<RunResponse> {
  const response = await requestJson('/api/research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: request.message }),
    signal,
    // 后端任务总时限为 20 秒，留出接收终态响应的时间。
    timeout: 30_000,
  })

  return response as RunResponse
}
