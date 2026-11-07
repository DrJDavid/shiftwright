// Rule names for people (PUNCHLIST B6): law rules by their law-pack `summary`, store rules by their `note` (or a
// description built only from their own params), role tags by their contracts ROLE_TAGS label. Never invented.
import type { Constraint, LawRule, StoreConfig } from '../contracts'
import { placeLabel } from './format'
import { ROLE_TAG_LABEL, tagLabel } from './vocab'

export function describeConstraint(c: Constraint, config: StoreConfig): string {
  if (c.note) return c.note
  const names = new Map(config.employees.map((e) => [e.id, e.name]))
  const roles = new Map(config.roles.map((r) => [r.id, r.name]))
  const p = (c.params ?? {}) as Record<string, unknown>
  const n = (id: unknown) => names.get(String(id)) ?? String(id)
  const hrs = (m: unknown) => `${Number(m) / 60} hours`
  switch (c.kind) {
    case 'min_shift_length':
      return `Shifts are at least ${hrs(p.minutes)}.`
    case 'max_shift_length':
      return `Shifts are at most ${hrs(p.minutes)}.`
    case 'min_rest_between_shifts':
      return `At least ${hrs(p.minutes)} between shifts.`
    case 'max_days_per_week':
      return `At most ${String(p.days)} days a week.`
    case 'max_consecutive_days':
      return `At most ${String(p.days)} days in a row.`
    case 'min_hours_week':
      return 'Give people their minimum hours.'
    case 'not_together':
      return `${((p.employee_ids as unknown[]) ?? []).map(n).join(' and ')} not on the same shift.`
    case 'fair_spread':
      return `At most ${String(p.max_per_employee)} ${String(p.shift_class)} shifts per person.`
    case 'always_staffed':
      return `${roles.get(String(p.role_id)) ?? String(p.role_id)} always staffed.`
    case 'preferred_role':
      return `${n(p.employee_id)} prefers ${roles.get(String(p.role_id)) ?? String(p.role_id)}.`
    case 'week_stability':
      return 'Keep the week close to last week.'
  }
  return String(c.kind).replace(/_/g, ' ')
}

/** "Chicago minimum wage rule": place from the rule's own jurisdiction, kind from its type. For inline text. */
export function shortLawName(r: LawRule): string {
  const place = r.level === 'federal' ? 'Federal' : r.level === 'city' ? placeLabel(r.jurisdiction.city, null) : r.jurisdiction.state
  return `${place} ${r.type.replace(/_/g, ' ')} rule`
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

export type RuleNames = {
  /** Full name for a law rule or store rule id (law summary / constraint note); unknown ids get spaces for underscores. */
  name: (id: string) => string
  /** Swap law rule ids, ROLE_TAGS ids and "N-min slots" in API prose for plain words. */
  plain: (text: string) => string
}

export function ruleNames(config: StoreConfig, lawRules: LawRule[] = []): RuleNames {
  const law = new Map(lawRules.map((r) => [r.id, r]))
  const constraints = new Map((config.constraints ?? []).map((c) => [c.id, c]))
  const lawRx = law.size ? new RegExp(`(${[...law.keys()].map(escape).join('|')})(?!\\w|\\.\\w)`, 'g') : null
  const tagRx = new RegExp(`\\b(${Object.keys(ROLE_TAG_LABEL).join('|')})\\b`, 'g')
  return {
    name: (id) => {
      const r = law.get(id)
      if (r) return r.summary
      const c = constraints.get(id)
      if (c) return describeConstraint(c, config)
      return id.replace(/_/g, ' ')
    },
    plain: (text) => {
      let t = text
      if (lawRx) t = t.replace(lawRx, (id) => shortLawName(law.get(id)!))
      t = t.replace(tagRx, (tag) => tagLabel(tag))
      return t.replace(/\b(\d+)-min slots\b/g, '$1-minute time blocks')
    },
  }
}
