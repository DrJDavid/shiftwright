// SEMANTICS #25: rule weights and role gap penalties are ranks, not prices, so people see words, never dollars.
import type { Constraint, Role } from '../contracts'

export type StrengthChoice = 'firm' | 'strong' | 'preference' | 'not_a_rule'

/** The words the rule card offers, and what each sends (C3b: the server and agent use exactly these weights). */
export const STRENGTHS: { id: StrengthChoice; label: string; hint: string; decision: 'hard' | 'soft' | 'not_a_rule'; weight?: number }[] = [
  { id: 'firm', label: 'Firm rule', hint: 'The schedule never breaks it.', decision: 'hard' },
  { id: 'strong', label: 'Strong preference', hint: 'Broken only when keeping it would leave a shift uncovered.', decision: 'soft', weight: 50 },
  { id: 'preference', label: 'Preference', hint: 'Broken only to cover a shift or to keep a strong preference.', decision: 'soft', weight: 25 },
  { id: 'not_a_rule', label: 'Not a rule', hint: 'Coincidence. Don’t use it.', decision: 'not_a_rule' },
]

export const STRONG_PREFERENCE_WEIGHT = 50

export function strengthChoice(c: Pick<Constraint, 'strength' | 'weight_dollars'>): StrengthChoice {
  if (c.strength === 'hard') return 'firm'
  return (c.weight_dollars ?? 0) >= STRONG_PREFERENCE_WEIGHT ? 'strong' : 'preference'
}

export const strengthLabel = (c: Pick<Constraint, 'strength' | 'weight_dollars'>) => STRENGTHS.find((s) => s.id === strengthChoice(c))!.label

/** C3b's fixed tier values; anything else (older or hand-tuned stores) is named by its rank among the store's roles. */
const TIER_LABEL: Record<number, string> = { 300: 'Must cover', 200: 'Important', 100: 'Nice to have' }

export function priorityLabel(role: Pick<Role, 'gap_penalty_per_hour'>, roles: Pick<Role, 'gap_penalty_per_hour'>[]): string {
  const v = role.gap_penalty_per_hour
  if (!(v > 0)) return 'Not set'
  const named = roles.every((r) => !(r.gap_penalty_per_hour > 0) || TIER_LABEL[r.gap_penalty_per_hour])
  if (named) return TIER_LABEL[v]
  const tiers = [...new Set(roles.map((r) => r.gap_penalty_per_hour).filter((x) => x > 0))].sort((a, b) => b - a)
  const rank = tiers.indexOf(v) + 1
  return tiers.length === 1 ? 'Covered' : rank === 1 ? `Covered first (1 of ${tiers.length})` : `${rank} of ${tiers.length}`
}
