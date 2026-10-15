import { useState } from "react"
import type { TargetClarification } from "./type"

interface ResearchClarificationProps {
    clarification: TargetClarification
    submitting: boolean
    errorMessage: string | null
    onSubmit: (answer: string[]) => void
}

export function ResearchClarification(props: ResearchClarificationProps) {
    const [answers, setAnswers] = useState<string[]>(
        () => props.clarification.ambiguous_targets.map(() => '')
    )
    const [additionalAnswer, setAdditionalAnswer] = useState('')
    const unresolved = props.clarification.unresolved_mentions.join('、')
    const answer = [...answers, additionalAnswer]
        .map(value => value.trim())
        .filter(Boolean)

    const updateAnswer = (index: number, value: string) => {
        const newAnswers = [...answers]
        newAnswers[index] = value
        setAnswers(newAnswers)
    }

    const submit = () => {
        if (answer.length === 0) return
        props.onSubmit(answer)
    }
    return (
        <div className="space-y-3">
            <p className="text-sm text-slate-200">以下信息需要二次确认</p>
            <fieldset disabled={props.submitting} className="min-w-0 space-y-3">
                {props.clarification.ambiguous_targets.map((target, index) => (
                    <div key={index} className="flex flex-wrap items-center gap-3">
                        <span className="text-sm text-slate-200">{target.mention}</span>
                        {target.candidates.map(candidate => (
                            <label
                                key={candidate}
                                role="button"
                                tabIndex={0}
                                aria-pressed={answers[index] === candidate}
                                onClick={() => updateAnswer(index, candidate)}
                                className={`cursor-pointer rounded-lg px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-cyan-300 ${
                                    answers[index] === candidate
                                        ? 'bg-cyan-400 text-slate-950'
                                        : 'bg-slate-800 text-slate-100'
                                }`}
                            >
                                {candidate}
                            </label>
                        ))}
                        <input
                            type="text"
                            aria-label={`${target.mention}的股票代号`}
                            placeholder="自行输入股票代号"
                            value={answers[index]}
                            onChange={event => updateAnswer(index, event.target.value)}
                            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-slate-900 p-3 text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400 disabled:opacity-60"
                        />
                    </div>
                ))}
                <input
                    type="text"
                    aria-label="未识别股票的股票代号"
                    placeholder={`请确认${unresolved}是否是要研究的股票，是请输入股票代号`}
                    value={additionalAnswer}
                    onChange={event => setAdditionalAnswer(event.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-slate-900 p-3 text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400 disabled:opacity-60"
                />
                <button
                    type="button"
                    onClick={submit}
                    disabled={props.submitting || answer.length === 0}
                    className="rounded-xl bg-cyan-400 px-5 py-3 font-medium text-slate-950 hover:bg-cyan-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {props.submitting ? '提交中…' : '确认'}
                </button>
            </fieldset>
        </div>
    )
}
