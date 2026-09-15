/**
 * 当前文件逐字段对应 FastAPI 的公开 Pydantic 模型。
 * 它只描述 D06 已存在的契约，不提前加入来源、行情、决策或风险字段。
 */

export type DataMode = 'fixture' | 'historical' | 'live'

/**
 * 后端要求 as_of 是带时区的 ISO 8601 字符串。
 * TypeScript 不能仅靠 string 类型验证时区，运行时校验仍以后端为准。
 */
export interface ResearchRequest {
  readonly company_id: string
  readonly question: string
  readonly data_mode: DataMode
  readonly as_of: string
}

export interface EvidenceClaim {
  readonly text: string
  readonly evidence_ids: readonly string[]
}

interface ResearchOutputBase {
  readonly facts: readonly EvidenceClaim[]
  readonly inferences: readonly EvidenceClaim[]
  readonly missing_information: readonly string[]
  readonly data_mode: DataMode
}

export interface CompletedResearchOutput extends ResearchOutputBase {
  readonly status: 'completed'
}

export interface InsufficientInformationResearchOutput
  extends ResearchOutputBase {
  readonly status: 'insufficient_information'
}

export type ResearchOutput =
  | CompletedResearchOutput
  | InsufficientInformationResearchOutput

export type RunStatus =
  | 'completed'
  | 'insufficient_information'
  | 'failed'
  | 'cancelled'

export type ErrorCode =
  | 'invalid_json'
  | 'invalid_output'
  | 'invalid_evidence'
  | 'data_mode_mismatch'
  | 'incomplete_response'
  | 'model_refusal'
  | 'invalid_tool_call'
  | 'model_timeout'
  | 'model_error'
  | 'tool_timeout'
  | 'total_timeout'
  | 'cancelled'
  | 'budget_exhausted'

export type ErrorStage = 'model' | 'tool' | 'validation' | 'task'

export interface PublicError {
  readonly code: ErrorCode
  readonly message: string
  readonly stage: ErrorStage
}

type NonCancelledErrorCode = Exclude<ErrorCode, 'cancelled'>

export interface CompletedRunResponse {
  readonly run_id: string
  readonly status: 'completed'
  readonly result: CompletedResearchOutput
  readonly error: null
}

export interface InsufficientInformationRunResponse {
  readonly run_id: string
  readonly status: 'insufficient_information'
  readonly result: InsufficientInformationResearchOutput
  readonly error: null
}

export interface FailedRunResponse {
  readonly run_id: string
  readonly status: 'failed'
  readonly result: null
  readonly error: PublicError & { readonly code: NonCancelledErrorCode }
}

export interface CancelledRunResponse {
  readonly run_id: string
  readonly status: 'cancelled'
  readonly result: null
  readonly error: PublicError & {
    readonly code: 'cancelled'
    readonly stage: 'task'
  }
}

/**
 * 可辨识联合类型把后端跨字段规则带到前端：
 * 成功终态一定有 result，失败/取消终态一定有 error。
 */
export type RunResponse =
  | CompletedRunResponse
  | InsufficientInformationRunResponse
  | FailedRunResponse
  | CancelledRunResponse

/** 按 status 从联合类型中提取对应的精确响应类型。 */
export type RunResponseFor<Status extends RunStatus> = Extract<
  RunResponse,
  { readonly status: Status }
>

export interface FastApiValidationIssue {
  readonly type: string
  readonly loc: readonly (string | number)[]
  readonly msg: string
  readonly input?: unknown
  readonly ctx?: Readonly<Record<string, unknown>>
  readonly url?: string
}

/** FastAPI 在请求体校验失败时返回的 HTTP 422 结构，不属于 RunResponse。 */
export interface FastApiValidationError {
  readonly detail: readonly FastApiValidationIssue[]
}
