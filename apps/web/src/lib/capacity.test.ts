import { describe, expect, it } from 'vitest'
import type { Schedule, StoreConfig } from '../contracts'
import { capacity } from './capacity'

const emp = (id: string, max: number, roles: string[]) => ({ id, name: id, max_hours_week: max, trained_role_ids: roles })
const cfg = {
  employees: [emp('a', 28, ['server']), emp('b', 28, ['server']), emp('c', 40, ['cook'])],
  roles: [
    { id: 'server', name: 'Server' },
    { id: 'cook', name: 'Cook' },
  ],
  demand: [{ role_id: 'server', day: 0, start: 600, end: 1320, headcount: 2 }, { role_id: 'cook', day: 0, start: 600, end: 1080, headcount: 1 }],
} as unknown as StoreConfig

describe('capacity', () => {
  it('adds up max hours and needed hours, and names the limit behind the gaps', () => {
    const sched = {
      shifts: [
        { employee_id: 'a', start: 0, end: 28 * 60 },
        { employee_id: 'b', start: 0, end: 27 * 60 },
      ],
      gaps: [
        {
          role_id: 'server', day: 0, start: 1080, end: 1320, missing_headcount: 2,
          reasons: [{ employee_id: 'a', code: 'at_max_hours' }, { employee_id: 'b', code: 'at_max_hours' }, { employee_id: 'c', code: 'not_trained' }],
        },
      ],
    } as unknown as Schedule
    const c = capacity(cfg, sched)
    expect(c.maxHours).toBe(96)
    expect(c.neededHours).toBe(24 + 8)
    expect(c.gapHours).toBe(8)
    expect(c.mainCause).toBe('max_hours')
    expect(c.roles).toEqual([{ roleId: 'server', name: 'Server', gapHours: 8, trained: 2, atMax: 2 }])
  })

  it('prefers the real limit over "already working another role"', () => {
    const sched = {
      shifts: [],
      gaps: [{ role_id: 'cook', day: 0, start: 600, end: 660, missing_headcount: 1, reasons: [{ code: 'already_assigned' }, { code: 'unavailable' }] }],
    } as unknown as Schedule
    expect(capacity(cfg, sched).mainCause).toBe('availability')
  })
})
