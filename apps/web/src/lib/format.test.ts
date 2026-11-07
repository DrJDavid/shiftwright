import { describe, expect, it } from 'vitest'
import { fmtDayDate, fmtHours, fmtMoney, fmtRange, fmtTime } from './format'

describe('fmtTime (12-hour local, never raw minutes)', () => {
  it('formats on-the-hour and half-hour times', () => {
    expect(fmtTime(390)).toBe('6:30a')
    expect(fmtTime(480)).toBe('8a')
    expect(fmtTime(720)).toBe('12p')
    expect(fmtTime(0)).toBe('12a')
    expect(fmtTime(1335)).toBe('10:15p')
  })
  it('wraps overnight times past 1440', () => {
    expect(fmtTime(1830)).toBe('6:30a')
  })
  it('formats ranges', () => {
    expect(fmtRange(390, 900)).toBe('6:30a–3p')
  })
})

describe('fmtMoney / fmtHours', () => {
  it('formats dollars with thousands separators', () => {
    expect(fmtMoney(1234)).toBe('$1,234')
    expect(fmtMoney(1234.5, { cents: true })).toBe('$1,234.50')
  })
  it('formats hours compactly', () => {
    expect(fmtHours(7.5)).toBe('7.5h')
    expect(fmtHours(40)).toBe('40h')
  })
})

describe('fmtDayDate', () => {
  it('turns day index + Monday week_start into a weekday label', () => {
    expect(fmtDayDate('2026-11-09', 0)).toEqual({ weekday: 'Mon', date: 'Nov 9' })
    expect(fmtDayDate('2026-11-09', 6)).toEqual({ weekday: 'Sun', date: 'Nov 15' })
  })
})

import { humanizer } from './humanize'
describe('humanizer', () => {
  it('swaps ids for names and 24h times for 12h', () => {
    const h = humanizer({
      employees: [{ id: 'e004', name: 'Val Martin' }],
      roles: [{ id: 'leader_on_duty', name: 'Leader on Duty' }],
    } as never)
    expect(h('Extend e004 from 12:30–22:00 as leader_on_duty; IL.chicago.predictive_scheduling.1')).toBe(
      'Extend Val Martin from 12:30p–10p as Leader on Duty; IL.chicago.predictive_scheduling.1',
    )
  })
})
