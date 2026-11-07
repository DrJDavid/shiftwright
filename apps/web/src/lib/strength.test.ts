import { describe, expect, it } from 'vitest'
import { priorityLabel, strengthLabel } from './strength'
import { costLabel } from './format'

describe('strengthLabel', () => {
  it('names rules by strength word; soft weights ≥ 50 are strong preferences', () => {
    expect(strengthLabel({ strength: 'hard' })).toBe('Firm rule')
    expect(strengthLabel({ strength: 'soft', weight_dollars: 50 })).toBe('Strong preference')
    expect(strengthLabel({ strength: 'soft', weight_dollars: 120 })).toBe('Strong preference')
    expect(strengthLabel({ strength: 'soft', weight_dollars: 25 })).toBe('Preference')
    expect(strengthLabel({ strength: 'soft' })).toBe('Preference')
  })
})

describe('priorityLabel', () => {
  it('uses the level names for the fixed tier values', () => {
    const roles = [{ gap_penalty_per_hour: 300 }, { gap_penalty_per_hour: 200 }, { gap_penalty_per_hour: 100 }]
    expect(roles.map((r) => priorityLabel(r, roles))).toEqual(['Must cover', 'Important', 'Nice to have'])
  })

  it('ranks other values without showing them', () => {
    const roles = [{ gap_penalty_per_hour: 45 }, { gap_penalty_per_hour: 30 }, { gap_penalty_per_hour: 45 }]
    expect(roles.map((r) => priorityLabel(r, roles))).toEqual(['Covered first (1 of 2)', '2 of 2', 'Covered first (1 of 2)'])
  })
})

describe('costLabel (tradeoff cards: real money only)', () => {
  it('shows added pay, savings and no-cost plainly', () => {
    expect(costLabel(86.6)).toBe('+$87')
    expect(costLabel(-40)).toBe('saves $40')
    expect(costLabel(0.2)).toBe('No extra cost')
    expect(costLabel(undefined)).toBe('')
  })
})
