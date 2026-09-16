import type { RunTransport } from '../api/runTransport'
import { getMockRunResponse } from './runResponses'

export const fakeRunTransport: RunTransport = {
  async createRun() {
    return getMockRunResponse('completed')
  },
}
