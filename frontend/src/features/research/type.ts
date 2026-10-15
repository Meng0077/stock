import type { ResearchStage, RunResponse } from '../../api/contracts'

export type ResearchViewState =
  | {
      readonly kind: 'idle'
    }
  | {
      readonly kind: 'submitting'
      readonly requestId: number
      readonly userMessage: string
    }
  | {
      readonly kind: 'received'
      readonly requestId: number
      readonly userMessage: string
      readonly response: RunResponse
    }
  | {
      readonly kind: 'request_failed'
      readonly requestId: number
      readonly userMessage: string
      readonly errorMessage: string
    }

export type ResearchHistoryEntry = Exclude<
  ResearchViewState,
  { readonly kind: 'idle' | 'submitting' }
>

export type ResearchRoundStatus =
    | 'submitting'
    | 'researching'
    | 'needs_input'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'request_failed'
    | 'stream_failed'
    | 'display_failed'
    | 'cancelling'

export interface ResearchTextContent {
    readonly type: 'text'
    readonly text: string
}

export interface ResearchCardContent{
    readonly type: 'card'
    readonly description: string
}

export interface ResearchClarificationAnswerContent {
    readonly type: 'clarification_answer'
    readonly text: string[]
}

export type ResearchContent =
    | ResearchTextContent
    | ResearchCardContent
    | ResearchClarificationAnswerContent

export interface TargetClarification {
    readonly type: 'target_clarification'
    readonly message: string
    readonly ambiguous_targets: readonly {
        readonly mention: string
        readonly candidates: readonly string[]
    }[]
    readonly unresolved_mentions: readonly string[]
}

export interface ResearchRound {
    readonly id: number;
    readonly threadId: string | null
    readonly question: string,
    readonly status: ResearchRoundStatus,
    readonly stage?: ResearchStage | null,
    readonly contents: ResearchContent[]
    readonly errorMessage: string | null,
    readonly clarification: TargetClarification | null
    readonly clarificationSubmitting: boolean
    readonly clarificationErrorMessage: string | null
    readonly pendingClarificationAnswer: string[] | null
}
