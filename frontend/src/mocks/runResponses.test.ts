import { describe, expect, it } from 'vitest'

import {
  getMockRunResponse,
  getMockValidationError,
  MOCK_DATA_NOTICE,
} from './runResponses'

describe('run response fixtures', () => {
  it.each([
    'completed',
    'insufficient_information',
    'failed',
    'cancelled',
  ] as const)('返回 %s 终态并保持字段组合合法', (status) => {
    const response = getMockRunResponse(status)

    expect(response.status).toBe(status)
    if (response.status === 'completed') {
      expect(response.result.status).toBe('completed')
      expect(response.result.facts.length).toBeGreaterThan(0)
      expect(response.error).toBeNull()
    } else if (response.status === 'insufficient_information') {
      expect(response.result.status).toBe('insufficient_information')
      expect(response.result.missing_information.length).toBeGreaterThan(0)
      expect(response.error).toBeNull()
    } else {
      expect(response.result).toBeNull()
      expect(response.error).not.toBeNull()
    }
  })

  it('成功 mock 派生自 D06 示例并明确是 fixture', () => {
    const response = getMockRunResponse('completed')

    expect(response.run_id).toBe('e990e7e2-90b7-4a49-b7f4-ebab4d05a581')
    expect(response.result.data_mode).toBe('fixture')
    expect(response.result.facts[0]?.evidence_ids).toContain('E1')
    expect(response.result.facts[1]?.evidence_ids).toContain('E2')
    expect(MOCK_DATA_NOTICE).toContain('不是实时行情或投资建议')
  })

  it('每次返回独立副本，不污染后续测试', () => {
    const first = getMockRunResponse('completed')
    const firstFacts = first.result.facts as unknown as Array<{
      text: string
      evidence_ids: string[]
    }>
    firstFacts[0] = { text: '被调用方修改', evidence_ids: ['E0'] }

    const second = getMockRunResponse('completed')
    expect(second.result.facts[0]?.text).not.toBe('被调用方修改')
  })

  it('提供与 D06 示例一致的 HTTP 422 mock', () => {
    const response = getMockValidationError()

    expect(response.detail).toHaveLength(1)
    expect(response.detail[0]).toMatchObject({
      type: 'string_too_short',
      loc: ['body', 'question'],
      input: '   ',
      ctx: { min_length: 1 },
    })
  })

  it('失败 mock 只包含公开错误，不包含原始异常', () => {
    const response = getMockRunResponse('failed')
    const serialized = JSON.stringify(response)

    expect(response.error).toEqual({
      code: 'model_error',
      message: '模型调用失败。',
      stage: 'model',
    })
    expect(serialized).not.toMatch(/traceback|api[_ -]?key|secret/i)
  })
})
