import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Toast } from './toast'


describe('Toast', () => {
  it('显示提示消息', () => {
    render(<Toast message="取消研究请求失败，请稍后重试。" />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      '取消研究请求失败，请稍后重试。',
    )
  })

  it('没有消息时不渲染', () => {
    const { container } = render(<Toast message={null} />)

    expect(container).toBeEmptyDOMElement()
  })
})
