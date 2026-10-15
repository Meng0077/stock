import type { ResearchCommandResponse, ResumeResearchRequest, StartResearchRequest } from './contracts'
import { post } from './request'

export async function startResearch(
    data: StartResearchRequest,
    signal?: AbortSignal,
): Promise<ResearchCommandResponse> {
    return post('/api/research', data, { signal })
}

export async function resumeResearch(
    data: ResumeResearchRequest,
    signal?: AbortSignal,
): Promise<ResearchCommandResponse> {
    return post('/api/research/resume', data, { signal })
}
