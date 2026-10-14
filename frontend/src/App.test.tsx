import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('显示研究页面', () => {
    render(
      <MemoryRouter initialEntries={['/research']}>
        <App />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('heading', {
        name: '对话式股票研究',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('在下方输入问题，开始一轮研究。')).toBeInTheDocument()
  })
})
