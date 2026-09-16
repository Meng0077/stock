import type { ResearchViewState } from './type'
import { ResearchResponse } from './ResearchResponse'

interface ResearchConversationProps {
  readonly state: ResearchViewState
}

export function ResearchConversation({ state }: ResearchConversationProps) {
  return (
    <section
      aria-label="研究对话"
      data-state={state.kind}
      className="grid min-w-0 gap-4"
    >
      {state.kind === 'idle' ? (
        <p className="rounded-3xl border border-dashed border-white/10 p-8 text-center text-slate-400">
          在下方输入问题，开始一轮研究。
        </p>
      ) : (
        <>
          {state.userMessage && (
            <article className="ml-auto max-w-full rounded-2xl rounded-br-sm bg-cyan-400/15 px-5 py-4 sm:max-w-[85%]">
              <p className="whitespace-pre-wrap break-words text-slate-100">{state.userMessage}</p>
            </article>
          )}

          {state.kind === 'submitting' && (
            <p role="status" className="rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-slate-300">
              Agent 正在整理研究结果，请稍候…
            </p>
          )}

          {state.kind === 'received' && (
            <ResearchResponse response={state.response} />
          )}

          {state.kind === 'request_failed' && (
            <div role="alert" className="rounded-2xl bg-red-400/10 px-5 py-4 text-red-100">
              <h2 className="font-medium">请求失败</h2>
              <p className="mt-2">{state.errorMessage}</p>
            </div>
          )}
        </>
      )}
    </section>
  )
}
