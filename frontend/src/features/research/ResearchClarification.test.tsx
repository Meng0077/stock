import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ResearchClarification } from './ResearchClarification'


const clarification = {
  type: 'target_clarification' as const,
  message: '请选择 Google 对应的股票。',
  ambiguous_targets: [{ mention: 'Google', candidates: ['GOOG', 'GOOGL'] }],
  unresolved_mentions: [],
}


afterEach(cleanup)


describe('ResearchClarification', () => {
  it('答案为空时不允许提交', () => {
    render(
      <ResearchClarification
        clarification={clarification}
        submitting={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '确认' })).toBeDisabled()
  })

  it('选择股票代号后提交非空答案', () => {
    const onSubmit = vi.fn()
    render(
      <ResearchClarification
        clarification={clarification}
        submitting={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'GOOGL' }))
    fireEvent.click(screen.getByRole('button', { name: '确认' }))

    expect(onSubmit).toHaveBeenCalledWith(['GOOGL'])
  })
})
