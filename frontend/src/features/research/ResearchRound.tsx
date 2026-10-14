import type { ResearchRound } from './type'
import type { ResearchStage } from '../../api/contracts'

interface ResearchRoundProps {
    readonly round: ResearchRound
}

function UserMessage({ question }: { question: string }) {
    return <article className="ml-auto max-w-full rounded-2xl rounded-br-sm bg-cyan-400/15 px-5 py-4 sm:max-w-[85%]">
            <p className="whitespace-pre-wrap break-words text-slate-100">
                {question}
            </p>
        </article>
}

const STAGE_LABELS:
    Record<ResearchStage, string> = {
    target_resolution:
        '正在识别研究标的…',

    planning:
        '正在制定研究计划…',

    research:
        '正在收集研究信息…',

    checking:
        '正在检查研究结果…',

    answering:
        '正在生成回答…',
}

function AssistantMessage({round}: { round: ResearchRound }) {
    if (round.status === 'submitting'){
        return <div role="status">正在创建研究任务…</div>
    }

    if (['request_failed', 'stream_failed', 'display_failed', 'failed'].includes(round.status)) {
        return <div
                role="alert"
                className="rounded-2xl bg-red-400/10 px-5 py-4 text-red-100"
            >
                { round?.errorMessage ?? '研究任务发生错误。'}
            </div>
    }

    if (round.status === 'cancelled') {
        return <div role="status">研究任务已取消。</div>
    }

    if (round.status === 'needs_input') {
        return <div role="status">需要补充信息后才能继续研究。</div>
    }

    if (round.contents.length > 0) {
        return round.contents.map((item, index) => {
            switch (item.type) {
                case 'text':
                    return (
                        <p
                            key={index}
                            className="whitespace-pre-wrap break-words"
                        >
                            {item.text}
                        </p>
                    )
                }
        })
    }

    if (round.stage) {
        return <div>{STAGE_LABELS[round.stage]}</div>
    }

    return <div role="status">正在开始研究…</div>
}

export function ResearchRound({ round }: ResearchRoundProps) {
    return (
        <section
        aria-label="一轮研究"
        data-state={round.status}
        className="grid min-w-0 gap-4"
        >
            <UserMessage question={round.question} />

            <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl bg-slate-900 px-4 py-3 text-slate-100">
                    <AssistantMessage round={round} />
                </div>
            </div>
        </section>
    )
}
