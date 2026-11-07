import { describe, expect, it } from 'vitest'
import type { Role } from '../contracts'
import { dayGroupDays, dayGroupLabel, shiftWage } from './vocab'

describe('v1.5 vocab', () => {
  it('parses day groups', () => {
    expect(dayGroupDays('all')).toEqual([0, 1, 2, 3, 4, 5, 6])
    expect(dayGroupDays('weekend')).toEqual([5, 6])
    expect(dayGroupDays('fri,sat')).toEqual([4, 5])
    expect(dayGroupDays('tue')).toEqual([1])
    expect(dayGroupDays('lunch', [{ id: 'lunch', days: [2] }])).toEqual([2])
    expect(dayGroupLabel('fri,sat')).toBe('Fri, Sat')
    expect(dayGroupLabel('mon,tue,wed')).toBe('Mon–Wed')
  })
  it('tipped wage only when every segment is a tipped role (#20)', () => {
    const roles = new Map<string, Role>([
      ['server', { id: 'server', tipped: true } as Role],
      ['host', { id: 'host', tipped: false } as Role],
    ])
    const e = { wage_per_hour: 16, tipped_wage_per_hour: 9.5 } as never
    expect(shiftWage({ segments: [{ role_id: 'server' }] } as never, e, roles)).toEqual({ wage: 9.5, tipped: true })
    expect(shiftWage({ segments: [{ role_id: 'server' }, { role_id: 'host' }] } as never, e, roles)).toEqual({ wage: 16, tipped: false })
  })
})
