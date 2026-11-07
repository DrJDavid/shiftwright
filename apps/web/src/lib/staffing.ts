// department_staffing → demand, exactly per contracts/API.md v1.3:
// base across open hours per day; peaks replace base inside their windows; open/close crews in the
// pre-open/post-close windows. The server does the real conversion; the web uses this for the live
// "Preview" heatmap and the mock API.
import type { DayHours } from '../contracts'
import type { DepartmentStaffingProps, RoleStaffing } from '../api/protocol'
import { dayGroupDays } from './vocab'

export type Interval = { role_id: string; day: number; start: number; end: number; headcount: number }

type Groups = { id: string; days: number[] }[]

/** Headcount for one role on day `day` at minute t. A peak applies on the days of its day_group (v1.5 values). */
export function staffAt(r: RoleStaffing, day: number, hours: DayHours | undefined, t: number, groups?: Groups): number {
  if (!hours || hours.close <= hours.open) return 0
  if (r.open && t >= hours.open - r.open.minutes_before_open && t < hours.open) return r.open.headcount
  if (r.close && t >= hours.close && t < hours.close + r.close.minutes_after_close) return r.close.headcount
  if (t < hours.open || t >= hours.close) return 0
  const peak = r.peaks.find((p) => p.start <= t && t < p.end && dayGroupDays(p.day_group, groups).includes(day))
  return peak ? peak.headcount : r.base
}

/** Demand intervals (one per constant run, at `step` granularity) for every day in the day groups. */
export function staffingToIntervals(
  props: Pick<DepartmentStaffingProps, 'day_groups' | 'hours'>,
  staffing: Record<string, RoleStaffing>,
  step = 5,
): Interval[] {
  const out: Interval[] = []
  const days = [...new Set(props.day_groups.flatMap((g) => g.days))].sort((a, b) => a - b)
  for (const day of days) {
    const h = props.hours.find((x) => x.day === day)
    if (!h || h.close <= h.open) continue
    for (const [role_id, r] of Object.entries(staffing)) {
      const lo = h.open - (r.open?.minutes_before_open ?? 0)
      const hi = h.close + (r.close?.minutes_after_close ?? 0)
      let cur: Interval | null = null
      for (let t = lo; t < hi; t += step) {
        const n = staffAt(r, day, h, t, props.day_groups)
        if (cur && cur.headcount === n && cur.end === t) cur.end = t + step
        else {
          if (cur && cur.headcount > 0) out.push(cur)
          cur = { role_id, day, start: t, end: t + step, headcount: n }
        }
      }
      if (cur && cur.headcount > 0) out.push(cur)
    }
  }
  return out
}

/** "2–4" style range of headcounts a role uses across base, peaks and crews. */
export function headcountRange(r: RoleStaffing): [number, number] {
  const ns = [r.base, ...r.peaks.map((p) => p.headcount), r.open?.headcount ?? r.base, r.close?.headcount ?? r.base].filter((n) => n > 0)
  return ns.length ? [Math.min(...ns), Math.max(...ns)] : [0, 0]
}
