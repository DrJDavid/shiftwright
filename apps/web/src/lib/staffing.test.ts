import { describe, expect, it } from 'vitest'
import type { RoleStaffing } from '../api/protocol'
import { headcountRange, staffAt, staffingToIntervals } from './staffing'

const hours = [{ day: 0, open: 480, close: 1320 }, { day: 5, open: 480, close: 1320 }]
const r: RoleStaffing = {
  base: 2,
  peaks: [{ day_group: 'weekday', start: 660, end: 840, headcount: 4 }],
  open: { headcount: 1, minutes_before_open: 60 },
  close: { headcount: 2, minutes_after_close: 30 },
}

describe('department_staffing conversion (API.md v1.3)', () => {
  it('base over open hours, peaks replace base, crews outside open hours', () => {
    expect(staffAt(r, 'weekday', hours[0], 430)).toBe(1) // opening crew 7a-8a
    expect(staffAt(r, 'weekday', hours[0], 400)).toBe(0)
    expect(staffAt(r, 'weekday', hours[0], 600)).toBe(2)
    expect(staffAt(r, 'weekday', hours[0], 700)).toBe(4) // peak 11a-2p weekdays
    expect(staffAt(r, 'saturday', hours[1], 700)).toBe(2) // peak is weekday-only
    expect(staffAt(r, 'weekday', hours[0], 1330)).toBe(2) // closing crew 10p-10:30p
    expect(staffAt(r, 'weekday', hours[0], 1350)).toBe(0)
  })
  it('emits one interval per constant run', () => {
    const iv = staffingToIntervals({ day_groups: [{ id: 'weekday', days: [0] }], hours }, { cashier: r }, 30)
    expect(iv.map((x) => [x.start, x.end, x.headcount])).toEqual([
      [420, 480, 1],
      [480, 660, 2],
      [660, 840, 4],
      [840, 1350, 2], // base and closing crew are both 2: one run
    ])
    expect(headcountRange(r)).toEqual([1, 4])
  })
})
