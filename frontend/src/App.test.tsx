import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('显示工程初始化状态', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', {
        name: 'React、TypeScript、Vite 与 Tailwind CSS 已就绪',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('工程初始化完成')).toBeInTheDocument()
    expect(screen.getByText(/FE01 已完成对话请求契约/)).toBeInTheDocument()
  })
})
