import type { Schedule, StoreConfig } from '../contracts'

/** Why the week has gaps, from the engine's own per-person gap reasons (GapReasonCode). */
export type Cause = 'max_hours' | 'availability' | 'budget' | 'training' | 'rules' | 'busy' | 'short_window'

const CAUSE: Record<string, Cause> = {
  at_max_hours: 'max_hours',
  unavailable: 'availability',
  budget_cap: 'budget',
  not_trained: 'training',
  law_rule: 'rules',
  minor_rule: 'rules',
  rest_rule: 'rules',
  already_assigned: 'busy',
  cheaper_to_leave_gap: 'short_window',
}

export type RoleShort = { roleId: string; name: string; gapHours: number; trained: number; atMax: number }
export type Capacity = {
  /** Most hours the whole team can work this week (sum of each person's max). */
  maxHours: number
  /** Hours of staffing the demand asks for. */
  neededHours: number
  gapHours: number
  /** The most common reason across gaps, weighted by hours. */
  mainCause: Cause | null
  roles: RoleShort[]
}

const hours = (start: number, end: number) => Math.max(0, end - start) / 60

export function capacity(config: StoreConfig, schedule: Schedule | null): Capacity {
  const maxHours = config.employees.reduce((a, e) => a + (e.max_hours_week ?? 40), 0)
  const neededHours = config.demand.reduce((a, d) => a + hours(d.start, d.end) * d.headcount, 0)
  const worked = new Map<string, number>()
  for (const s of schedule?.shifts ?? []) worked.set(s.employee_id, (worked.get(s.employee_id) ?? 0) + hours(s.start, s.end))

  const causeHours = new Map<Cause, number>()
  const roleGap = new Map<string, number>()
  let gapHours = 0
  for (const g of schedule?.gaps ?? []) {
    const h = hours(g.start, g.end) * (g.missing_headcount ?? 1)
    gapHours += h
    roleGap.set(g.role_id, (roleGap.get(g.role_id) ?? 0) + h)
    const counts = new Map<Cause, number>()
    for (const r of g.reasons ?? []) {
      const c = CAUSE[r.code]
      if (c) counts.set(c, (counts.get(c) ?? 0) + 1)
    }
    // "busy" (working another role) is a symptom; prefer the limit behind it when there is one.
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || (a[0] === 'busy' ? 1 : -1))
    if (ranked[0]) causeHours.set(ranked[0][0], (causeHours.get(ranked[0][0]) ?? 0) + h)
  }
  const mainCause = [...causeHours.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null

  const roles = [...roleGap.entries()]
    .map(([roleId, gap]) => {
      const people = config.employees.filter((e) => e.trained_role_ids.includes(roleId))
      return {
        roleId,
        name: config.roles.find((r) => r.id === roleId)?.name ?? roleId,
        gapHours: gap,
        trained: people.length,
        atMax: people.filter((e) => (worked.get(e.id) ?? 0) >= (e.max_hours_week ?? 40) - 2).length,
      }
    })
    .sort((a, b) => b.gapHours - a.gapHours)
  return { maxHours, neededHours, gapHours, mainCause, roles }
}
