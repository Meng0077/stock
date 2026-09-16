import type {
  CancelledRunResponse,
  CompletedRunResponse,
  CreateResearchRunRequest,
  FailedRunResponse,
  FastApiValidationError,
  InsufficientInformationRunResponse,
  RunResponse,
  RunStatus,
} from '../api/contracts'

/** 所有 FE01 mock 都是本地教学数据，不代表真实行情或投资建议。 */
export const MOCK_DATA_NOTICE =
  '本地 fixture 教学模拟数据，不是实时行情或投资建议。'

const runResponses = {
  completed: {
    run_id: 'e990e7e2-90b7-4a49-b7f4-ebab4d05a581',
    status: 'completed',
    result: {
      status: 'completed',
      facts: [
        {
          text: '公司资料（证据 E1，本地教学模拟数据）：company_id 为 NVDA，公司名称为 NVIDIA（英伟达），描述为“教学用简化公司介绍：提供 GPU 及相关计算平台，用于图形处理和人工智能计算”。',
          evidence_ids: ['E1'],
        },
        {
          text: '报价（证据 E2，本地教学模拟数据）：NVDA 的价格为 100.0 USD，quoted_at 为 2026-09-11T09:00:00+08:00；该记录明确标注为“固定虚构报价，仅用于验证工具调用；报价时间也是预设的教学时间”。',
          evidence_ids: ['E2'],
        },
        {
          text: '两条证据的 data_mode 均为 fixture，来源标注为“本地教学模拟数据”，因此以上价格与公司描述均为本地教学模拟数据，不是实时行情、真实报价或投资建议。',
          evidence_ids: ['E1', 'E2'],
        },
      ],
      inferences: [
        {
          text: '根据 E1 的业务描述可推断，该公司属于 GPU 与计算平台（含图形处理、人工智能计算）相关业务领域；此为公司定位层面的推断，不涉及任何行情或估值判断。',
          evidence_ids: ['E1'],
        },
        {
          text: '证据的可用信息时点为 2026-09-11T09:00:00+08:00，早于 as_of（2026-09-15T16:00:00+08:00），因此这些数据只能视为 as_of 之前的历史快照，无法用于描述 as_of 时刻的状态。',
          evidence_ids: ['E1', 'E2'],
        },
      ],
      missing_information: [
        '缺少除 fixture 报价外的任何价格序列、成交量、市值、估值指标等数据。',
        '缺少公司财务数据（营收、利润、利润率、指引）与业务分部构成等基本面信息。',
        '缺少公司公告、财报发布日期、行业与竞争格局等基本面资料。',
        '缺少真实（非模拟）行情数据，无法进行实时报价或投资判断。',
        '工具仅支持 NVDA，无法获取其他公司或宏观、行业对照数据。',
      ],
      data_mode: 'fixture',
    },
    error: null,
  },
  insufficient_information: {
    run_id: '7d33b5a3-c17f-463a-b11f-448ebdf4d9ca',
    status: 'insufficient_information',
    result: {
      status: 'insufficient_information',
      facts: [],
      inferences: [],
      missing_information: ['当前 fixture 没有该公司的资料。'],
      data_mode: 'fixture',
    },
    error: null,
  },
  failed: {
    run_id: '7f5b9409-c7b9-46a5-bd84-f3a4b4c342b4',
    status: 'failed',
    result: null,
    error: {
      code: 'model_error',
      message: '模型调用失败。',
      stage: 'model',
    },
  },
  cancelled: {
    run_id: '2e758faf-8522-433a-bcda-a876a641ae99',
    status: 'cancelled',
    result: null,
    error: {
      code: 'cancelled',
      message: '任务已取消。',
      stage: 'task',
    },
  },
} satisfies Record<RunStatus, RunResponse>

const validationError = {
  detail: [
    {
      type: 'string_too_short',
      loc: ['body', 'message'],
      msg: 'String should have at least 1 character',
      input: '   ',
      ctx: { min_length: 1 },
    },
  ],
} satisfies FastApiValidationError

const createRunRequest = {
  message: '帮我看看英伟达最近怎么样',
} satisfies CreateResearchRunRequest

/**
 * 输入运行终态，输出一份独立的固定 RunResponse。
 * structuredClone 避免调用方修改共享 mock，readonly 类型避免正常代码误改字段。
 */
export function getMockRunResponse(status: 'completed'): CompletedRunResponse
export function getMockRunResponse(
  status: 'insufficient_information',
): InsufficientInformationRunResponse
export function getMockRunResponse(status: 'failed'): FailedRunResponse
export function getMockRunResponse(status: 'cancelled'): CancelledRunResponse
export function getMockRunResponse(status: RunStatus): RunResponse
export function getMockRunResponse(status: RunStatus): RunResponse {
  return structuredClone(runResponses[status])
}

/** 输出一份独立的 FastAPI HTTP 422 fixture。 */
export function getMockValidationError(): FastApiValidationError {
  return structuredClone(validationError)
}

/** 输出一份只含用户自然语言的公开对话请求 fixture。 */
export function getMockCreateResearchRunRequest(): CreateResearchRunRequest {
  return structuredClone(createRunRequest)
}
