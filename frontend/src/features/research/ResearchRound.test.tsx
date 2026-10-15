import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
  clarification: null,
  clarificationSubmitting: false,
  clarificationErrorMessage: null,
  pendingClarificationAnswer: null,
  ...updates,
})


afterEach(cleanup)


describe('ResearchRound', () => {
  it('无文字内容时显示当前研究阶段', () => {
    render(<ResearchRoundView round={makeRound({ stage: 'planning' })} submitAnswer={vi.fn()} cancel={vi.fn()} />)

    expect(screen.getByText('制定研究计划')).toBeInTheDocument()
  })

  it('显示已累积的回答文字', () => {
    render(<ResearchRoundView round={makeRound({
      status: 'completed',
      contents: [{ type: 'text', text: 'NVDA 研究结果' }],
    })} submitAnswer={vi.fn()} cancel={vi.fn()} />)

    expect(screen.getByText('NVDA 研究结果')).toBeInTheDocument()
  })

  it('展示层失败使用 alert 提示', () => {
    render(<ResearchRoundView round={makeRound({
      status: 'display_failed',
      errorMessage: '研究结果展示失败，请稍后重试。',
    })} submitAnswer={vi.fn()} cancel={vi.fn()} />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      '研究结果展示失败，请稍后重试。',
    )
  })

  it('研究中可以发起取消', () => {
    const cancel = vi.fn()
    render(
      <ResearchRoundView
        round={makeRound()}
        submitAnswer={vi.fn()}
        cancel={cancel}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '停止研究' }))

    expect(cancel).toHaveBeenCalledWith(1)
  })

  it('取消请求处理中禁用按钮', () => {
    render(
      <ResearchRoundView
        round={makeRound({ status: 'cancelling' })}
        submitAnswer={vi.fn()}
        cancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '取消中...' })).toBeDisabled()
  })

  it('取消终态显示明确状态', () => {
    render(
      <ResearchRoundView
        round={makeRound({ status: 'cancelled' })}
        submitAnswer={vi.fn()}
        cancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('任务已取消。')
    expect(screen.queryByRole('button', { name: '停止研究' })).not.toBeInTheDocument()
  })

  it('needs_input 显示澄清表单且不显示停止按钮', () => {
    render(
      <ResearchRoundView
        round={makeRound({
          status: 'needs_input',
          clarification: {
            type: 'target_clarification',
            message: '请选择 Google 对应的股票。',
            ambiguous_targets: [{ mention: 'Google', candidates: ['GOOG', 'GOOGL'] }],
            unresolved_mentions: [],
          },
        })}
        submitAnswer={vi.fn()}
        cancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '确认' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '停止研究' })).not.toBeInTheDocument()
  })

  it.each([
    ['request_failed', '请求启动失败'],
    ['stream_failed', '研究连接中断'],
    ['display_failed', '研究结果展示失败'],
    ['failed', '后端研究失败'],
  ] as const)('%s 显示对应的安全错误', (status, errorMessage) => {
    render(
      <ResearchRoundView
        round={makeRound({ status, errorMessage })}
        submitAnswer={vi.fn()}
        cancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(errorMessage)
    expect(screen.queryByRole('button', { name: '停止研究' })).not.toBeInTheDocument()
  })
})
