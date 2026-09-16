import type { CreateResearchRunRequest, RunResponse } from './contracts'

export type CreateRun = (
  request: CreateResearchRunRequest,
  signal?: AbortSignal,
) => Promise<RunResponse>

export interface RunTransport {
  readonly createRun: CreateRun
}
