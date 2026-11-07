import { describe, expect, it } from 'vitest'
import { dayCoveragePct } from './dayCoverage'

describe('dayCoveragePct (SEMANTICS #1, one day)', () => {
  const config = { demand: [{ id: 'd', role_id: 'cashier', day: 5, start: 480, end: 600, headcount: 2, source: 'leader' }] } as never
  const sched = (shifts: object[]) => ({ shifts }) as never
  it('min(demand, people) per minute', () => {
    const a = { employee_id: 'a', day: 5, start: 480, end: 600, segments: [{ role_id: 'cashier', start: 480, end: 600 }] }
    const b = { employee_id: 'b', day: 5, start: 540, end: 600, segments: [{ role_id: 'cashier', start: 540, end: 600 }] }
    expect(dayCoveragePct(config, sched([a, b]), 5)).toBeCloseTo(75)
    expect(dayCoveragePct(config, sched([a, b]), 5, ['b'])).toBeCloseTo(50)
    expect(dayCoveragePct(config, sched([a]), 4)).toBeNull()
  })
})
