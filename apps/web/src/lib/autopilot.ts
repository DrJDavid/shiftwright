import type { CardType } from '../api/protocol'

/** PUNCHLIST B7: routine cards autopilot submits as prefilled. */
export const AUTO_CARDS: ReadonlySet<CardType> = new Set<CardType>([
  'csv_import',
  'store_basics',
  'payroll',
  'roles',
  'training_matrix',
  'department_staffing',
  'events',
])

/** Decisions stay with the user: never auto-submitted, whatever else changes. */
export const DECISION_CARDS: ReadonlySet<CardType> = new Set<CardType>(['confirm_tags', 'propose_rule', 'tradeoff', 'conflict_menu'])

export const isAutoCard = (t: CardType) => AUTO_CARDS.has(t) && !DECISION_CARDS.has(t)

export const AUTOPILOT_DELAY_MS = 2000
