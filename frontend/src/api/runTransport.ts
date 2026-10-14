import type { ResearchCommandResponse, StartResearchRequest } from './contracts'
import { post } from './request'

export async function startResearch(
    request: StartResearchRequest,
    signal?: AbortSignal,
): Promise<ResearchCommandResponse> {
    return post('/api/research', request, { signal })
}
