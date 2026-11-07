// Display names for v1.5 vocabularies. Names only: which tags a law bans comes from the law pack.
import type { Employee, EventKind, Role, Sector, Shift } from '../contracts'
import { WEEKDAY_NAMES } from './format'

/** contracts ROLE_TAGS (v1.5) → friendly names. Unknown tags fall back to the tag with spaces. */
export const ROLE_TAG_LABEL: Record<string, string> = {
  powered_industrial_truck: 'Forklift / powered industrial truck',
  meat_slicer: 'Meat slicer',
  bakery_machine: 'Bakery machine',
  baler_compactor: 'Baler / compactor',
  motor_vehicle_driving: 'Driving',
  cooking: 'Cooking',
  fryer: 'Fryer',
  power_saw: 'Power saw',
  ladder_scaffold: 'Ladder / scaffold',
  alcohol_service: 'Alcohol service',
}
export const tagLabel = (t: string) => ROLE_TAG_LABEL[t] ?? t.replace(/_/g, ' ')

export const SECTOR_LABEL: Record<Sector, string> = {
  retail: 'Retail store',
  food: 'Restaurant, café or bar',
  hospitality: 'Hotel or lodging',
  other: 'Something else',
}

export const EVENT_LABEL: Record<EventKind, string> = {
  truck: 'Truck',
  floor_set: 'Floor set',
  promo: 'Promo',
  online_surge: 'Online surge',
  delivery: 'Delivery',
  private_event: 'Private event',
  catering: 'Catering',
  other: 'Event',
}

/** Kinds relevant to the business first (API.md v1.5); every kind stays valid. */
export function eventKindsFor(sector: Sector | null | undefined): EventKind[] {
  const food: EventKind[] = ['delivery', 'private_event', 'catering']
  const retail: EventKind[] = ['truck', 'floor_set', 'promo', 'online_surge']
  const first = sector === 'food' || sector === 'hospitality' ? food : sector === 'retail' ? retail : []
  const all = Object.keys(EVENT_LABEL) as EventKind[]
  return [...first, ...all.filter((k) => !first.includes(k))]
}

export const eventName = (e: { kind: EventKind; label?: string }) => e.label?.trim() || EVENT_LABEL[e.kind] || e.kind

const SHORT = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

/** v1.5 day_group values → day indexes: all, weekday, weekend, saturday, sunday, mon…sun, comma lists. */
export function dayGroupDays(g: string, known?: { id: string; days: number[] }[]): number[] {
  const hit = known?.find((x) => x.id === g)
  if (hit) return hit.days
  const out = new Set<number>()
  for (const part of g.split(',').map((p) => p.trim().toLowerCase())) {
    if (part === 'all') [0, 1, 2, 3, 4, 5, 6].forEach((d) => out.add(d))
    else if (part === 'weekday') [0, 1, 2, 3, 4].forEach((d) => out.add(d))
    else if (part === 'weekend') [5, 6].forEach((d) => out.add(d))
    else if (part === 'saturday') out.add(5)
    else if (part === 'sunday') out.add(6)
    else if (SHORT.includes(part.slice(0, 3))) out.add(SHORT.indexOf(part.slice(0, 3)))
  }
  return [...out].sort((a, b) => a - b)
}

export function dayGroupLabel(g: string, known?: { id: string; days: number[] }[]): string {
  const named: Record<string, string> = { all: 'Every day', weekday: 'Weekdays', weekend: 'Weekends', saturday: 'Saturday', sunday: 'Sunday' }
  if (named[g]) return named[g]
  const days = dayGroupDays(g, known)
  if (days.length === 1) return WEEKDAY_NAMES[days[0]]
  if (days.length > 2 && days.every((d, i) => i === 0 || d === days[i - 1] + 1)) return `${WEEKDAY_NAMES[days[0]]}–${WEEKDAY_NAMES[days.at(-1)!]}`
  return days.map((d) => WEEKDAY_NAMES[d]).join(', ') || g
}

/** SEMANTICS #20: tipped iff every segment is a tipped role and the employee has a tipped wage. */
export function shiftWage(s: Shift, e: Employee, roles: Map<string, Role>): { wage: number; tipped: boolean } {
  const tipped = e.tipped_wage_per_hour != null && s.segments.length > 0 && s.segments.every((g) => roles.get(g.role_id)?.tipped === true)
  return tipped ? { wage: e.tipped_wage_per_hour!, tipped } : { wage: e.wage_per_hour, tipped: false }
}
