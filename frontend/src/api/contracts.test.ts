import { describe, expect, expectTypeOf, it } from 'vitest'

import type {
  CancelledRunResponse,
  CompletedRunResponse,
  FastApiValidationError,
  ResearchRequest,
  RunResponse,
} from './contracts'

describe('API contracts', () => {
  it('描述当前 ResearchRequest 的四个公开字段', () => {
    const request: ResearchRequest = {
      company_id: 'NVDA',
      question: '查询教学报价',
      data_mode: 'fixture',
      as_of: '2026-09-15T16:00:00+08:00',
    }

    expect(Object.keys(request)).toEqual([
      'company_id',
      'question',
      'data_mode',
      'as_of',
    ])
  })

  it('通过联合类型区分成功和取消响应', () => {
    expectTypeOf<CompletedRunResponse>().toMatchTypeOf<RunResponse>()
    expectTypeOf<CancelledRunResponse>().toMatchTypeOf<RunResponse>()
    expectTypeOf<CompletedRunResponse['result']>().not.toBeNull()
    expectTypeOf<CancelledRunResponse['result']>().toBeNull()
  })

  it('单独描述 FastAPI HTTP 422 响应', () => {
    const response: FastApiValidationError = {
      detail: [
        {
          type: 'string_too_short',
          loc: ['body', 'question'],
          msg: 'String should have at least 1 character',
          input: '   ',
          ctx: { min_length: 1 },
        },
      ],
    }

    expect(response.detail[0]?.loc).toEqual(['body', 'question'])
  })
})
