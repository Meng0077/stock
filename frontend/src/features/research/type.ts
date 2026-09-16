import type { RunResponse } from '../../api/contracts'

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
