// Display formatting. Contract times are minutes after local midnight (may exceed 1440).

export function fmtTime(minutes: number): string {
  const m = ((minutes % 1440) + 1440) % 1440
  const h24 = Math.floor(m / 60)
  const mm = m % 60
  const suffix = h24 < 12 ? 'a' : 'p'
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12
  return mm === 0 ? `${h12}${suffix}` : `${h12}:${String(mm).padStart(2, '0')}${suffix}`
}

export function fmtRange(start: number, end: number): string {
  return `${fmtTime(start)}–${fmtTime(end)}`
}

const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

export function fmtMoney(dollars: number, opts: { cents?: boolean } = {}): string {
  return (opts.cents ? usd2 : usd0).format(dollars)
}

/** Compact money for tight spaces: $950, $8.8k. */
export function fmtMoneyShort(dollars: number): string {
  return Math.abs(dollars) >= 1000 ? `$${(dollars / 1000).toFixed(1)}k` : usd0.format(dollars)
}

export function fmtHours(hours: number): string {
  const r = Math.round(hours * 10) / 10
  return `${Number.isInteger(r) ? r.toFixed(0) : r.toFixed(1)}h`
}

export function fmtPct(pct: number): string {
  return `${(Math.round(pct * 10) / 10).toFixed(pct >= 99.95 || pct === 0 ? 0 : 1)}%`
}

/** Coverage with nothing to cover is "—", not the engine's vacuous 100%. */
export function fmtCoverage(pct: number, demand: { headcount: number }[]): string {
  return demand.some((d) => d.headcount > 0) ? fmtPct(pct) : '—'
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** `weekStart` is an ISO date (always a Monday); `day` is 0..6. Computed in UTC to avoid DST drift. */
export function fmtDayDate(weekStart: string, day: number): { weekday: string; date: string } {
  const [y, mo, d] = weekStart.split('-').map(Number)
  const dt = new Date(Date.UTC(y, mo - 1, d + day))
  return { weekday: WEEKDAYS[day] ?? `Day ${day}`, date: `${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}` }
}

export const WEEKDAY_NAMES = WEEKDAYS

/** "Chicago, IL" from a jurisdiction (cities are stored lower-case). */
export function placeLabel(city: string | null | undefined, state: string | null | undefined): string {
  const c = city ? city.replace(/\b\w/g, (ch) => ch.toUpperCase()) : ''
  return [c, state].filter(Boolean).join(', ')
}
