import { ResearchComposer } from '../features/research/ResearchComposer'
import { ResearchRound } from '../features/research/ResearchRound'
import { Toast } from '../features/research/toast'
import { useResearchRun } from '../features/research/useResearchRun'

export function ResearchPage() {
  const { rounds, toastMessage, submit, reset, submitAnswer, cancel } = useResearchRun()

  const isSubmitting = rounds[rounds.length - 1]?.status === 'submitting'

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto grid w-full min-w-0 max-w-4xl gap-6">
        <header>
          <p className="text-sm font-semibold tracking-[0.2em] text-cyan-300 uppercase">
            Stock Agent
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            对话式股票研究
          </h1>
          <p className="mt-3 max-w-2xl text-slate-400">
            输入自然语言问题。当前使用后端教学模拟数据，不代表实时行情或投资建议。
          </p>
        </header>
        {
          rounds.length === 0 ? (
            <p className="rounded-3xl border border-dashed border-white/10 p-8 text-center text-slate-400">
              在下方输入问题，开始一轮研究。
            </p>
          ) : (
            rounds.map((round) => (
              <ResearchRound key={round.id} round={round} submitAnswer={submitAnswer} cancel={cancel} />
            ))
          )
        }

        {rounds.length > 0 && (
          <button
            type="button"
            onClick={reset}
            className="justify-self-end rounded-lg px-2 py-1 text-sm text-slate-400 underline underline-offset-4 hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-cyan-300"
          >
            清空全部对话
          </button>
        )}

        <section aria-label="提交研究问题" className="rounded-3xl border border-white/10 bg-white/5 p-4 shadow-2xl shadow-cyan-950/20 sm:p-6">
          <ResearchComposer
            disabled={isSubmitting}
            onSubmit={submit}
          />
        </section>
        <Toast message={toastMessage} />
      </div>
    </main>
  )
}
