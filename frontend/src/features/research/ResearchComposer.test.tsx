import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ResearchComposer } from './ResearchComposer'


afterEach(cleanup)


describe('ResearchComposer', () => {
  it('空字符串和纯空格不提交', () => {
    const onSubmit = vi.fn()
    render(<ResearchComposer disabled={false} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('提交去除首尾空格后的自然语言问题', () => {
    const onSubmit = vi.fn()
    render(<ResearchComposer disabled={false} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: '  NVDA 怎么看  ' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(onSubmit).toHaveBeenCalledWith({ message: 'NVDA 怎么看' })
  })

  it('submitting 时禁止重复提交', () => {
    const onSubmit = vi.fn()
    render(<ResearchComposer disabled onSubmit={onSubmit} />)

    expect(screen.getByLabelText('研究问题')).toBeDisabled()
    expect(screen.getByRole('button', { name: '研究中…' })).toBeDisabled()
  })
})
