import type { ResearchRound } from './type'
import { ResearchProgress } from './ResearchProgress'
import { ResearchClarification } from './ResearchClarification'

interface ResearchRoundProps {
    readonly round: ResearchRound
    readonly submitAnswer: (roundId: number, answer: string[]) => void
    readonly cancel: (roundId: number) => void
}

function UserMessage({ question }: { question: string }) {
    return <article className="ml-auto max-w-full rounded-2xl rounded-br-sm bg-cyan-400/15 px-5 py-4 sm:max-w-[85%]">
            <p className="whitespace-pre-wrap break-words text-slate-100">
                {question}
            </p>
        </article>
}

function AssistantMessage({round}: { round: ResearchRound }) {
    if (round.errorMessage) {
        return <p role="alert" className="text-red-300">{round.errorMessage}</p>
    }

    if (round.contents.length > 0) {
        return round.contents.map((item, index) => {
            switch (item.type) {
                case 'text':
                    return (
                        <p
                            key={index}
                            className="whitespace-pre-wrap break-words leading-7"
                        >
                            {item.text}
                        </p>
                    )
                case 'clarification_answer':
                    return (
                        <div key={index} className="space-y-2">
                            <p className="text-sm text-slate-400">补充信息：</p>
                            <div className="flex flex-wrap gap-2">
                                {item.text.map((text, answerIndex) => (
                                    <span
                                        key={answerIndex}
                                        className="max-w-full whitespace-pre-wrap break-words rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-sm font-medium text-cyan-200"
                                    >
                                        {text}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )
            }
        })
    }
}

export function ResearchRound({ round, submitAnswer, cancel }: ResearchRoundProps) {
    return (
        <section
        aria-label="一轮研究"
        data-state={round.status}
        className="grid min-w-0 gap-4"
        >
            <UserMessage question={round.question} />

            <ResearchProgress status={round.status} stage={round.stage || null} />

            {(round.status === 'researching' || round.status === 'cancelling') && (
                <button
                    type="button"
                    disabled={round.status === 'cancelling'}
                    onClick={() => {cancel(round.id)}}
                    className="justify-self-start rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-400 hover:border-red-400/30 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {round.status === 'cancelling' ? '取消中...' : '停止研究'}
                </button>
            )}

            <div className="flex justify-start">
                <div className="min-w-0 max-w-full space-y-4 rounded-2xl rounded-bl-sm bg-slate-900 px-5 py-4 text-slate-100 sm:max-w-[85%]">
                    <AssistantMessage round={round} />
                </div>
            </div>
            {
                round.status === 'needs_input' && round.clarification && (
                    <ResearchClarification
                        clarification={round.clarification}
                        submitting={round.clarificationSubmitting}
                        errorMessage={round.clarificationErrorMessage}
                        onSubmit={(answer) => {submitAnswer(round.id, answer)}}
                    />
                )
            }
            {round.status === 'cancelled' && (
                <p role="status" className="text-sm text-slate-500">
                    任务已取消。
                </p>
            )}
        </section>
    )
}
