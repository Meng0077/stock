import type { ResearchCommandResponse, StartResearchRequest } from '../api/contracts'

export const fakeStartResearch = async (
  request: StartResearchRequest,
): Promise<ResearchCommandResponse> => {
  void request
  return {
    thread_id: '00000000-0000-0000-0000-000000000040',
    status: 'accepted',
  }
}
