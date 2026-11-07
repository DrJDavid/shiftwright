import { describe, expect, it } from 'vitest'
import { ruleNames, shortLawName } from './ruleNames'

const config = {
  roles: [{ id: 'grill', name: 'Grill' }],
  employees: [
    { id: 'e1', name: 'Ana' },
    { id: 'e2', name: 'Ben' },
  ],
  constraints: [
    { id: 'c_note', kind: 'max_days_per_week', params: { days: 5 }, note: 'Nobody works six days.' },
    { id: 'c_apart', kind: 'not_together', params: { employee_ids: ['e1', 'e2'] } },
  ],
} as never

const chiWage = {
  id: 'IL.chicago.minimum_wage',
  level: 'city',
  type: 'minimum_wage',
  jurisdiction: { state: 'IL', city: 'chicago' },
  summary: 'Chicago minimum wage is $16.20/hour.',
} as never
const fedMinor = { id: 'US.minor_hours', level: 'federal', type: 'minor_hours', jurisdiction: { state: null, city: null }, summary: 'Under-16s work limited hours.' } as never

describe('ruleNames', () => {
  const rn = ruleNames(config, [chiWage, fedMinor])

  it('names law rules by their law-pack summary', () => {
    expect(rn.name('IL.chicago.minimum_wage')).toBe('Chicago minimum wage is $16.20/hour.')
  })

  it('names store rules by their note, else from their own params', () => {
    expect(rn.name('c_note')).toBe('Nobody works six days.')
    expect(rn.name('c_apart')).toBe('Ana and Ben not on the same shift.')
  })

  it('falls back to the id with spaces for unknown ids', () => {
    expect(rn.name('budget_cap')).toBe('budget cap')
  })

  it('swaps law ids, role tags and slot jargon in prose', () => {
    expect(rn.plain('Blocked by IL.chicago.minimum_wage.')).toBe('Blocked by Chicago minimum wage rule.')
    expect(rn.plain('Roles tagged powered_industrial_truck')).toBe('Roles tagged Forklift / powered industrial truck')
    expect(rn.plain('Demand uses 30-min slots')).toBe('Demand uses 30-minute time blocks')
  })

  it('builds short law names from the rule jurisdiction', () => {
    expect(shortLawName(chiWage)).toBe('Chicago minimum wage rule')
    expect(shortLawName(fedMinor)).toBe('Federal minor hours rule')
  })
})
