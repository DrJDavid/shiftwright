import { describe, expect, it } from 'vitest'
import type { Readiness } from '../api/protocol'
import { setupSteps } from './setupSteps'

const check = (id: string, ok: boolean, severity: 'ok' | 'warn' | 'block' = ok ? 'ok' : 'block') => ({
  id,
  label: id,
  ok,
  detail: `${id} detail`,
  severity,
})

describe('setupSteps', () => {
  it('groups the API readiness checks into Business → Hours & budget → Team → Staffing → Rules', () => {
    // Every id apps/api readiness.py emits, in its order.
    const r: Readiness = {
      ready: false,
      checks: [
        check('store_basics', true),
        check('jurisdiction', true),
        check('roles', true),
        check('employees', false),
        check('training', false),
        check('demand', true),
        check('priorities', true),
        check('equipment_roles', true, 'warn'),
        check('minors_on_tagged_roles', true),
        check('business_type', true),
        check('roles_without_demand', true),
        check('staffing_draft', true),
        check('budget', true),
        check('minimum_wage', true),
        check('provisional_rules', false, 'warn'),
      ],
    }
    const steps = setupSteps(r)
    expect(steps.map((s) => [s.label, s.checks.map((c) => c.id)])).toEqual([
      ['Business', ['store_basics', 'jurisdiction', 'business_type']],
      ['Hours & budget', ['budget']],
      ['Team', ['roles', 'employees', 'training', 'equipment_roles', 'minors_on_tagged_roles', 'minimum_wage']],
      ['Staffing', ['demand', 'priorities', 'roles_without_demand', 'staffing_draft']],
      ['Rules', ['provisional_rules']],
    ])
    expect(steps.map((s) => s.done)).toEqual([true, true, false, true, false])
    expect(steps.find((s) => s.id === 'team')!.attention).toBe(true)
    expect(steps.find((s) => s.id === 'rules')!.attention).toBe(true)
  })

  it('puts unknown checks under Rules and treats a step with no checks as not done', () => {
    const steps = setupSteps({ ready: true, checks: [check('something_new', false)] })
    expect(steps.find((s) => s.id === 'rules')!.checks.map((c) => c.id)).toEqual(['something_new'])
    expect(steps.find((s) => s.id === 'business')!.done).toBe(false)
    expect(setupSteps(null).every((s) => !s.done)).toBe(true)
  })
})
