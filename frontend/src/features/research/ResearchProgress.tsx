import type { ResearchStage } from "../../api/contracts"
import type { ResearchRoundStatus } from "./type"

interface ResearchProgressStep {
    stage: ResearchStage
    label: string
}

const RESEARCH_PROGRESS_STEPS: readonly ResearchProgressStep[] = [
    { stage: 'target_resolution', label: '理解研究目标' },
    { stage: 'planning', label: '制定研究计划' },
    { stage: 'research', label: '收集和分析信息' },
    { stage: 'checking', label: '检查研究结果' },
    { stage: 'answering', label: '生成回答' },
]

type ResearchProgressStepState =
  | 'completed'
  | 'active'
  | 'waiting'
  | 'pending'

export const ResearchProgress = ({ status, stage }: { status: ResearchRoundStatus, stage: ResearchStage | null }) => {
    // terminal / error 状态 不展示进度
    if (['completed', 'failed', 'cancelled', 'request_failed', 'stream_failed', 'display_failed'].includes(status)) {
        return null
    }

    if(status === 'submitting'){
        return <div>正在启动研究…</div>
    }
    if (stage === null) {
        // 'needs_input'
        if(status === 'needs_input'){
            return <div>等待补充信息</div>
        }

        // workflow 已开始，但第一条 stage_changed可能还没到。
        return <div>正在准备研究…</div>
    }


    const currentStep = RESEARCH_PROGRESS_STEPS.findIndex(item => item.stage === stage)
    // status = researching, stage != null
    return RESEARCH_PROGRESS_STEPS.map((step, index) => {
        let state: ResearchProgressStepState = 'waiting'
        if (index < currentStep) {
            state = 'completed'
        } else if (index > currentStep) {
            state = 'pending'
        } else if (status === 'needs_input') {
            state = 'waiting'
        } else {
            state = 'active'
        }
        return (
            <div key={step.stage}>
                {state === 'completed' && <span>✓ </span>}
                {state === 'active' && <span>● </span>}
                {state === 'waiting' && <span>◐ </span>}
                {state === 'pending' && <span>○ </span>}
                {step.label}
                {state ===  'waiting' && ' · 等待你补充信息'}
            </div>
        )
    })
}
