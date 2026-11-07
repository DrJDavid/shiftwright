// MOCK-ONLY: department_staffing props with suggestions read off the store's existing (fixture) demand,
// and applying a result back to demand with the same conversion the preview uses.
import type { DemandRequirement, StoreConfig } from '../contracts'
import type { DepartmentStaffingProps, RoleStaffing } from '../api/protocol'
import { staffingToIntervals } from '../lib/staffing'

const GROUPS = [
  { id: 'weekday', days: [0, 1, 2, 3, 4] },
  { id: 'saturday', days: [5] },
  { id: 'sunday', days: [6] },
]

export function mockStaffingProps(cfg: StoreConfig, departmentId: string): DepartmentStaffingProps {
  const dept = cfg.departments.find((d) => d.id === departmentId) ?? cfg.departments[0]
  const roles = cfg.roles.filter((r) => r.department_id === dept.id)
  const step = cfg.store.slot_minutes ?? 30
  const need = (rid: string, day: number, t: number) =>
    cfg.demand.filter((d) => d.role_id === rid && d.day === day && d.source !== 'event' && d.start <= t && t < d.end).reduce((n, d) => n + d.headcount, 0)
  const suggested: Record<string, RoleStaffing> = {}
  for (const r of roles) {
    const mon = cfg.store.hours.find((h) => h.day === 0)
    const s: RoleStaffing = { base: 1, peaks: [], open: null, close: null }
    if (mon) {
      const counts = new Map<number, number>()
      for (let t = mon.open; t < mon.close; t += step) counts.set(need(r.id, 0, t), (counts.get(need(r.id, 0, t)) ?? 0) + 1)
      s.base = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 1
      for (const g of GROUPS) {
        const day = g.days[0]
        const h = cfg.store.hours.find((x) => x.day === day)
        if (!h) continue
        let run: { start: number; end: number; headcount: number } | null = null
        for (let t = h.open; t <= h.close; t += step) {
          const n = t < h.close ? need(r.id, day, t) : -1
          if (run && n === run.headcount) run.end = t + step
          else {
            if (run && run.headcount > s.base) s.peaks.push({ day_group: g.id, ...run })
            run = n > s.base ? { start: t, end: t + step, headcount: n } : null
          }
        }
      }
      const before = cfg.demand.filter((d) => d.role_id === r.id && d.day === 0 && d.source !== 'event' && d.start < mon.open)
      if (before.length) s.open = { headcount: Math.max(...before.map((d) => d.headcount)), minutes_before_open: mon.open - Math.min(...before.map((d) => d.start)) }
      const after = cfg.demand.filter((d) => d.role_id === r.id && d.day === 0 && d.source !== 'event' && d.end > mon.close)
      if (after.length) s.close = { headcount: Math.max(...after.map((d) => d.headcount)), minutes_after_close: Math.max(...after.map((d) => d.end)) - mon.close }
    }
    suggested[r.id] = s
  }
  return {
    department: dept,
    roles,
    day_groups: GROUPS,
    hours: cfg.store.hours,
    pre_open_minutes: cfg.store.pre_open_minutes ?? 60,
    post_close_minutes: cfg.store.post_close_minutes ?? 60,
    suggested,
  }
}

/** Replaces non-event demand for the department's roles (API.md v1.3 conversion). */
export function applyStaffing(cfg: StoreConfig, props: DepartmentStaffingProps, staffing: Record<string, RoleStaffing>): StoreConfig {
  const roles = new Set(Object.keys(staffing))
  const keep = cfg.demand.filter((d) => !(roles.has(d.role_id) && d.source !== 'event'))
  const fresh: DemandRequirement[] = staffingToIntervals(props, staffing, cfg.store.slot_minutes ?? 30).map((x, i) => ({
    id: `dm_staff_${i}`,
    ...x,
    source: 'leader',
    note: 'department staffing',
  }))
  return { ...cfg, demand: [...keep, ...fresh] }
}
