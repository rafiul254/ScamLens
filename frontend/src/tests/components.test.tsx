import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import HighlightedText from '../components/HighlightedText'
import InputTabs from '../components/InputTabs'
import RiskGauge from '../components/RiskGauge'
import { translate, verdictKey } from '../lib/i18n'
import type { Analysis } from '../lib/types'

describe('InputTabs', () => {
  it('shows all four input tabs and submits typed text', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<InputTabs lang="en" busy={false} onSubmit={onSubmit} />)

    expect(screen.getByRole('tab', { name: /paste text/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /screenshot/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /voice/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /link/i })).toBeInTheDocument()

    await user.type(screen.getByRole('textbox'), 'You have won a prize, pay 500 taka')
    await user.click(screen.getByRole('button', { name: /check this message/i }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0].kind).toBe('text')
  })

  it('shows the PII badge when private details are present', async () => {
    const user = userEvent.setup()
    render(<InputTabs lang="en" busy={false} onSubmit={vi.fn()} />)
    await user.type(screen.getByRole('textbox'), 'send to 01712345678')
    expect(await screen.findByRole('status')).toHaveTextContent(/PII protected|hidden/i)
  })

  it('disables the submit button while busy', () => {
    render(<InputTabs lang="en" busy onSubmit={vi.fn()} />)
    expect(screen.getByRole('button', { name: /checking/i })).toBeDisabled()
  })
})

describe('RiskGauge', () => {
  it('exposes the real score to assistive technology', () => {
    render(<RiskGauge score={82} verdict="SCAM" label="Risk score" />)
    const meter = screen.getByRole('meter')
    expect(meter).toHaveAttribute('aria-valuenow', '82')
    expect(meter).toHaveAttribute('aria-label', 'Risk score')
  })
})

describe('HighlightedText', () => {
  const message = 'Congratulations! You won 5 lakh taka, pay 500 taka fee now.'

  it('marks the suspicious span returned by the API', () => {
    const { container } = render(
      <HighlightedText
        text={message}
        redFlags={[{ text_span: 'You won 5 lakh taka', reason: 'Prize claim', severity: 0.9 }]}
      />,
    )
    const marks = container.querySelectorAll('mark.flag')
    expect(marks).toHaveLength(1)
    expect(marks[0].textContent).toBe('You won 5 lakh taka')
    expect(marks[0].getAttribute('title')).toBe('Prize claim')
  })

  it('renders plain text when there are no flags', () => {
    const { container } = render(<HighlightedText text="Kal dekha hobe" redFlags={[]} />)
    expect(container.querySelectorAll('mark')).toHaveLength(0)
    expect(screen.getByText('Kal dekha hobe')).toBeInTheDocument()
  })

  it('highlights model tokens when the API supplies offsets', () => {
    const analysisPartial = {
      top_tokens: [{ token: 'pay 500 taka', contribution: 1, start: 41, end: 53, text: 'pay 500 taka' }],
    } as unknown as Analysis['evidence']
    const { container } = render(
      <HighlightedText text={message} redFlags={[]} evidence={analysisPartial} />,
    )
    expect(container.querySelectorAll('mark').length).toBeGreaterThan(0)
  })
})

describe('i18n', () => {
  it('falls back to English for missing keys and interpolates variables', () => {
    expect(translate('bn', 'home.analyze')).toBe('যাচাই করুন')
    expect(translate('ur', 'nav.home')).toBe('جانچ')
    expect(translate('bn', 'home.piiDetected', { n: 3 })).toContain('3')
    expect(translate('en', 'unknown.key')).toBe('unknown.key')
  })

  it('maps verdicts to translation keys', () => {
    expect(verdictKey('SCAM')).toBe('result.verdict.scam')
    expect(verdictKey('weird')).toBe('result.verdict.suspicious')
  })
})
