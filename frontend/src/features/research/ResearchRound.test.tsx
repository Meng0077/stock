import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ResearchRound as ResearchRoundView } from './ResearchRound'
import type { ResearchRound } from './type'


const makeRound = (updates: Partial<ResearchRound> = {}): ResearchRound => ({
  id: 1,
  threadId: 'thread-1',
  question: 'NVDA 怎么看',
  status: 'researching',
  stage: null,
  contents: [],
  errorMessage: null,
  ...updates,
})


describe('ResearchRound', () => {
  it('无文字内容时显示当前研究阶段', () => {
    render(<ResearchRoundView round={makeRound({ stage: 'planning' })} />)

    expect(screen.getByText('正在制定研究计划…')).toBeInTheDocument()
  })

  it('显示已累积的回答文字', () => {
    render(<ResearchRoundView round={makeRound({
      status: 'completed',
      contents: [{ type: 'text', text: 'NVDA 研究结果' }],
    })} />)

    expect(screen.getByText('NVDA 研究结果')).toBeInTheDocument()
  })

  it('展示层失败使用 alert 提示', () => {
    render(<ResearchRoundView round={makeRound({
      status: 'display_failed',
      errorMessage: '研究结果展示失败，请稍后重试。',
    })} />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      '研究结果展示失败，请稍后重试。',
    )
  })
})
