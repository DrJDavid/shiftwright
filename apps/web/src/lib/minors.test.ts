import { describe, expect, it } from 'vitest'
import { minorProtections } from './minors'

describe('minorProtections', () => {
  it('lists minors trained on roles a rule bars them from, with what they work instead', () => {
    const config = {
      store: { sector: 'food' },
      roles: [
        { id: 'line_cook', name: 'Line Cook' },
        { id: 'dish', name: 'Dishwasher' },
      ],
      role_tags: { line_cook: ['cooking', 'fryer'] },
      employees: [
        { id: 'e1', name: 'Tommy Ruiz', age: 15, trained_role_ids: ['line_cook', 'dish'] },
        { id: 'e2', name: 'Ann Adult', age: 30, trained_role_ids: ['line_cook'] },
      ],
    } as never
    const rule = { id: 'US.minor_prohibited_roles.7', type: 'minor_prohibited_roles', params: { age_below: 16, age_min: 14, role_tags: ['fryer'] } } as never
    const schedule = { shifts: [{ employee_id: 'e1', day: 5, segments: [{ role_id: 'dish' }] }] } as never
    const out = minorProtections(config, schedule, [rule])
    expect(out).toHaveLength(1)
    expect(out[0].employee.name).toBe('Tommy Ruiz')
    expect(out[0].barred[0].roles[0].tags).toEqual(['fryer'])
    expect(out[0].scheduledRoles.map((r) => r.name)).toEqual(['Dishwasher'])
    expect(out[0].workedBarred).toEqual([])
  })
})
