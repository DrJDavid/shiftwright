// "Minors kept off hazardous roles": for each minor trained on a role the law pack bars them from, what they
// were scheduled as instead. Facts only: ages and training from config, tags from config.role_tags, bans from
// the law pack's minor_prohibited_roles rules (age band + role_tags), roles worked from the schedule.
import type { Employee, LawRule, Role, Schedule, StoreConfig } from '../contracts'

export type Barred = { rule: LawRule; roles: { role: Role; tags: string[] }[] }
export type MinorProtection = {
  employee: Employee
  /** Rules that bar this employee from roles they are trained on. */
  barred: Barred[]
  /** Distinct roles this employee works this week. */
  scheduledRoles: Role[]
  /** Barred roles they were nonetheless scheduled in (should be empty; the validator reports these). */
  workedBarred: Role[]
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** SEMANTICS #19: a rule with `applies_to` applies to "both", the store's sector, or when the sector is unknown/other. */
function appliesToSector(rule: LawRule, config: StoreConfig): boolean {
  const to = (rule.params as Record<string, unknown> | undefined)?.applies_to
  const sector = config.store.sector
  if (typeof to !== 'string' || to === 'both' || !sector || sector === 'other') return true
  return to === sector
}

export function minorProtections(config: StoreConfig, schedule: Schedule | null, rules: LawRule[]): MinorProtection[] {
  const tagsOf = (config.role_tags ?? {}) as Record<string, string[]>
  const roleById = new Map(config.roles.map((r) => [r.id, r]))
  const banRules = rules.filter((r) => r.type === 'minor_prohibited_roles' && appliesToSector(r, config))
  const out: MinorProtection[] = []
  for (const e of config.employees) {
    const barred: Barred[] = []
    for (const rule of banRules) {
      const p = (rule.params ?? {}) as Record<string, unknown>
      const below = num(p.age_below)
      const floor = num(p.age_min) // v1.5 (#21)
      if (below == null || e.age >= below || (floor != null && e.age < floor)) continue
      const banned = Array.isArray(p.role_tags) ? (p.role_tags as string[]) : []
      const roles = e.trained_role_ids
        .map((id) => roleById.get(id))
        .filter((r): r is Role => !!r)
        .map((role) => ({ role, tags: (tagsOf[role.id] ?? []).filter((t) => banned.includes(t)) }))
        .filter((x) => x.tags.length > 0)
      if (roles.length) barred.push({ rule, roles })
    }
    if (!barred.length) continue
    const worked = new Set((schedule?.shifts ?? []).filter((s) => s.employee_id === e.id).flatMap((s) => s.segments.map((g) => g.role_id)))
    const barredIds = new Set(barred.flatMap((b) => b.roles.map((x) => x.role.id)))
    out.push({
      employee: e,
      barred,
      scheduledRoles: [...worked].map((id) => roleById.get(id)).filter((r): r is Role => !!r),
      workedBarred: [...worked].filter((id) => barredIds.has(id)).map((id) => roleById.get(id)!),
    })
  }
  return out.sort((a, b) => a.employee.age - b.employee.age || a.employee.name.localeCompare(b.employee.name))
}
