// Guided setup (PUNCHLIST B4): readiness checks grouped into the steps a leader walks through.
// Check ids are the ones apps/api/src/shiftwright_api/readiness.py emits.
import type { Readiness } from '../api/protocol'

export type StepId = 'business' | 'hours_budget' | 'team' | 'staffing' | 'rules'
export type Check = Readiness['checks'][number]

export const STEPS: { id: StepId; label: string; checks: string[] }[] = [
  { id: 'business', label: 'Business', checks: ['store_basics', 'jurisdiction', 'business_type'] },
  { id: 'hours_budget', label: 'Hours & budget', checks: ['budget'] },
  {
    id: 'team',
    label: 'Team',
    checks: ['roles', 'employees', 'training', 'equipment_roles', 'minors_on_tagged_roles', 'minimum_wage'],
  },
  { id: 'staffing', label: 'Staffing', checks: ['demand', 'priorities', 'roles_without_demand', 'staffing_draft'] },
  { id: 'rules', label: 'Rules', checks: ['provisional_rules'] },
]

export type StepState = {
  id: StepId
  label: string
  checks: Check[]
  /** Every check in the step passes (warnings keep `ok: true`, so they don't hold a step back). */
  done: boolean
  /** Something to look at: a warning, or only non-blocking checks still open. */
  attention: boolean
}

/** Checks the map doesn't know (a newer server) land in Rules, so nothing is hidden. */
export function setupSteps(readiness: Readiness | null): StepState[] {
  const checks = readiness?.checks ?? []
  const known = new Set(STEPS.flatMap((s) => s.checks))
  return STEPS.map((s) => {
    const mine = checks.filter((c) => s.checks.includes(c.id) || (s.id === 'rules' && !known.has(c.id)))
    return {
      id: s.id,
      label: s.label,
      checks: mine,
      done: mine.length > 0 && mine.every((c) => c.ok),
      attention: mine.some((c) => c.severity === 'warn'),
    }
  })
}
