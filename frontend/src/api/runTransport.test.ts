import { afterEach, describe, expect, it, vi } from 'vitest'

import { cancelResearch, resumeResearch, startResearch } from './runTransport'
import { post, request } from './request'


vi.mock('./request', () => ({
  post: vi.fn(),
  request: vi.fn(),
}))


afterEach(() => {
  vi.mocked(post).mockReset()
  vi.mocked(request).mockReset()
})


describe('runTransport', () => {
  it('启动和 Resume 使用各自的固定 API', async () => {
    vi.mocked(post).mockResolvedValue({ thread_id: 'thread-1', status: 'accepted' })
    const signal = new AbortController().signal

    await startResearch({ message: 'NVDA 怎么看' }, signal)
    await resumeResearch({ thread_id: 'thread-1', answer: ['NVDA'] }, signal)

    expect(post).toHaveBeenNthCalledWith(1, '/api/research', { message: 'NVDA 怎么看' }, { signal })
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/api/research/resume',
      { thread_id: 'thread-1', answer: ['NVDA'] },
      { signal },
    )
  })

  it('Cancel URL 使用当前 threadId 并保留 cancelling 响应', async () => {
    vi.mocked(request).mockResolvedValue({ thread_id: 'thread-1', status: 'cancelling' })
    const signal = new AbortController().signal

    await expect(cancelResearch('thread-1', signal)).resolves.toEqual({
      thread_id: 'thread-1',
      status: 'cancelling',
    })
    expect(request).toHaveBeenCalledWith('/api/research/thread-1/cancel', {
      method: 'POST',
      signal,
    })
  })
})
