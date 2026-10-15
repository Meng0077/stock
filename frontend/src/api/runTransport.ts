import type { CancelResearchResponse, ResearchCommandResponse, ResumeResearchRequest, StartResearchRequest } from './contracts'
import { post, request } from './request'

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

export async function cancelResearch(
    threadId: string,
    signal?: AbortSignal,
): Promise<CancelResearchResponse> {
    return request(
        `/api/research/${threadId}/cancel`,
        {
            method: 'POST',
            signal,
        },
    )
}
