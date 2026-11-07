// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ProposeRuleCard } from './ProposeRuleCard'

afterEach(cleanup)

const props = {
  constraint: { id: 'c1', kind: 'not_together', params: { employee_ids: ['e1', 'e2'] }, strength: 'soft', status: 'provisional', source: 'chat' },
  evidence: 'They never closed together in 8 weeks.',
  plain_text: 'Ana and Ben not on the same closing shift.',
} as never

function card() {
  const sent: unknown[] = []
  render(<ProposeRuleCard props={props} status="open" onSubmit={(r) => sent.push(r)} onCancel={() => {}} />)
  return sent
}

describe('ProposeRuleCard (C3: words, not dollars)', () => {
  it('offers exactly the four choices and no money field', () => {
    card()
    expect(screen.getAllByRole('radio').map((r) => r.closest('label')!.querySelector('.font-semibold')!.textContent)).toEqual([
      'Firm rule',
      'Strong preference',
      'Preference',
      'Not a rule',
    ])
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(document.body.textContent).not.toMatch(/\$/)
  })

  it.each([
    ['Firm rule', { decision: 'hard' }],
    ['Strong preference', { decision: 'soft', weight_dollars: 50 }],
    ['Preference', { decision: 'soft', weight_dollars: 25 }],
    ['Not a rule', { decision: 'not_a_rule' }],
  ])('%s sends %o', (label, expected) => {
    const sent = card()
    fireEvent.click(screen.getByLabelText(new RegExp(`^${label}`)))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(sent).toEqual([expected])
  })
})
