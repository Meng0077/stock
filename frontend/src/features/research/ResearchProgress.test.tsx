import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ResearchStage } from '../../api/contracts'
import { ResearchProgress } from './ResearchProgress'


afterEach(cleanup)


describe('ResearchProgress', () => {
  it.each([
    ['target_resolution', '理解研究目标'],
    ['planning', '制定研究计划'],
    ['research', '收集和分析信息'],
    ['checking', '检查研究结果'],
    ['answering', '生成回答'],
  ] as const)('显示 %s 阶段', (stage, label) => {
    render(<ResearchProgress status="researching" stage={stage as ResearchStage} />)

    expect(screen.getByText(label).parentElement).toHaveTextContent(`● ${label}`)
  })

  it('当前阶段之前的步骤显示为已完成', () => {
    render(<ResearchProgress status="researching" stage="research" />)

    expect(screen.getByText('理解研究目标').parentElement).toHaveTextContent('✓ 理解研究目标')
    expect(screen.getByText('制定研究计划').parentElement).toHaveTextContent('✓ 制定研究计划')
    expect(screen.getByText('收集和分析信息').parentElement).toHaveTextContent('● 收集和分析信息')
  })

  it.each(['completed', 'failed', 'cancelled', 'request_failed', 'stream_failed', 'display_failed'] as const)(
    '%s 终态不显示进度',
    (status) => {
      const { container } = render(<ResearchProgress status={status} stage="answering" />)

      expect(container).toBeEmptyDOMElement()
    },
  )
})
