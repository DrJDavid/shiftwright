// Day-level coverage, same definition as SEMANTICS #1 (per minute: covered = min(demand, people working the
// role), coverage = covered / required headcount-minutes), restricted to one day. Computed from the store's
// demand and a schedule's role segments; breaks are already outside segments.
import type { Schedule, StoreConfig } from '../contracts'

const STEP = 5 // every boundary (slots, 5-minute breaks) is a multiple of 5 minutes

export function dayCoveragePct(config: StoreConfig, schedule: Schedule | null | undefined, day: number, exclude: string[] = []): number | null {
  if (!schedule) return null
  const demand = config.demand.filter((d) => d.day === day)
  if (demand.length === 0) return null
  const shifts = (schedule.shifts ?? []).filter((s) => s.day === day && !exclude.includes(s.employee_id))
  let required = 0
  let covered = 0
  const roles = [...new Set(demand.map((d) => d.role_id))]
  for (const role of roles) {
    const rd = demand.filter((d) => d.role_id === role)
    const lo = Math.min(...rd.map((d) => d.start))
    const hi = Math.max(...rd.map((d) => d.end))
    const segs = shifts.flatMap((s) => s.segments.filter((g) => g.role_id === role))
    for (let t = lo; t < hi; t += STEP) {
      const need = rd.reduce((n, d) => (d.start <= t && t < d.end ? n + d.headcount : n), 0)
      if (!need) continue
      const have = segs.reduce((n, g) => (g.start <= t && t < g.end ? n + 1 : n), 0)
      required += need
      covered += Math.min(need, have)
    }
  }
  return required ? (covered / required) * 100 : null
}
