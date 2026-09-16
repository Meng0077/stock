import { describe, expect, expectTypeOf, it } from 'vitest'

import type {
  CancelledRunResponse,
  CompletedRunResponse,
  CreateResearchRunRequest,
  FastApiValidationError,
  RunResponse,
} from './contracts'

describe('API contracts', () => {
  it('对话请求只要求用户提供自然语言消息', () => {
    const request: CreateResearchRunRequest = {
      message: '帮我看看英伟达最近怎么样',
    }

    expect(Object.keys(request)).toEqual(['message'])
    expect(request).not.toHaveProperty('company_id')
    expect(request).not.toHaveProperty('data_mode')
    expect(request).not.toHaveProperty('as_of')
  })

  it('允许为未来多轮对话保留可选 conversation_id', () => {
    const request: CreateResearchRunRequest = {
      message: '我成本 220，最近适合继续加仓吗？',
      conversation_id: 'conversation-001',
    }

    expect(request.conversation_id).toBe('conversation-001')
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
          loc: ['body', 'message'],
          msg: 'String should have at least 1 character',
          input: '   ',
          ctx: { min_length: 1 },
        },
      ],
    }

    expect(response.detail[0]?.loc).toEqual(['body', 'message'])
  })
})
