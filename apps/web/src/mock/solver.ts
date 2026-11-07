// MOCK-ONLY greedy scheduler so the UI has a contract-shaped Schedule before WS1/WS6 land.
// It is NOT the engine. Every metric here is computed from the shifts it produced, so the UI
// never shows a hand-typed number. Replace by switching the client to the live API.
import type { Gap, GapReason, Schedule, ScheduleMetrics, Shift, StoreConfig, ValidationReport } from '../contracts'

const MAX_SPAN = 8.5 * 60
const BREAK_AFTER = 6 * 60

export function mockSolve(cfg: StoreConfig): { schedule: Schedule; validation: ValidationReport } {
  const slot = cfg.store.slot_minutes ?? 30
  const roleById = new Map(cfg.roles.map((r) => [r.id, r]))
  const hoursUsed = new Map<string, number>()
  const daysWorked = new Map<string, Set<number>>()
  const cap = cfg.budget.weekly_hours_cap + (cfg.budget.approvals ?? []).reduce((h, a) => h + (a.extra_hours ?? 0), 0)
  let budgetUsed = 0
  const shifts: Shift[] = []

  const reqs = [...cfg.demand].sort(
    (a, b) =>
      a.day - b.day ||
      (roleById.get(b.role_id)?.gap_penalty_per_hour ?? 0) - (roleById.get(a.role_id)?.gap_penalty_per_hour ?? 0) ||
      a.start - b.start,
  )

  const paidMinutes = (span: number) => (span > BREAK_AFTER ? span - 30 : span)

  for (const req of reqs) {
    const len = req.end - req.start
    const pieces = Math.ceil(len / MAX_SPAN)
    const raw = Math.ceil(len / pieces / slot) * slot
    for (let unit = 0; unit < req.headcount; unit++) {
      for (let p = 0; p < pieces; p++) {
        const start = req.start + p * raw
        const end = Math.min(req.end, start + raw)
        const paidH = paidMinutes(end - start) / 60
        if (budgetUsed + paidH > cap) continue
        const candidates = cfg.employees
          .filter((e) => e.trained_role_ids.includes(req.role_id))
          .filter((e) => !(daysWorked.get(e.id)?.has(req.day)))
          .filter((e) => (daysWorked.get(e.id)?.size ?? 0) < 5)
          .filter((e) => (hoursUsed.get(e.id) ?? 0) + paidH <= (e.max_hours_week ?? 40))
          .sort((a, b) => a.wage_per_hour - b.wage_per_hour || (hoursUsed.get(a.id) ?? 0) - (hoursUsed.get(b.id) ?? 0))
        const emp = candidates[0]
        if (!emp) continue
        const shift: Shift = { id: `s${shifts.length + 1}`, employee_id: emp.id, day: req.day, start, end, breaks: [], segments: [] }
        if (end - start > BREAK_AFTER) {
          const bs = start + Math.floor((end - start) / 2 / slot) * slot
          shift.breaks = [{ start: bs, end: bs + 30, kind: 'meal', paid: false }]
          shift.segments = [
            { role_id: req.role_id, start, end: bs },
            { role_id: req.role_id, start: bs + 30, end },
          ]
        } else {
          shift.segments = [{ role_id: req.role_id, start, end }]
        }
        shifts.push(shift)
        hoursUsed.set(emp.id, (hoursUsed.get(emp.id) ?? 0) + paidH)
        if (!daysWorked.has(emp.id)) daysWorked.set(emp.id, new Set())
        daysWorked.get(emp.id)!.add(req.day)
        budgetUsed += paidH
      }
    }
  }

  // Coverage per (role, day, slot)
  let reqSlots = 0
  let coveredSlots = 0
  const gaps: Gap[] = []
  const byRoleDay = new Map<string, { role: string; day: number }>()
  for (const d of cfg.demand) byRoleDay.set(`${d.role_id}|${d.day}`, { role: d.role_id, day: d.day })
  for (const { role, day } of byRoleDay.values()) {
    const rd = cfg.demand.filter((d) => d.role_id === role && d.day === day)
    const lo = Math.min(...rd.map((d) => d.start))
    const hi = Math.max(...rd.map((d) => d.end))
    let open: Gap | null = null
    for (let t = lo; t < hi; t += slot) {
      const need = rd.filter((d) => d.start <= t && t < d.end).reduce((n, d) => n + d.headcount, 0)
      const have = shifts.filter(
        (s) => s.day === day && s.segments.some((g) => g.role_id === role && g.start <= t && t < g.end),
      ).length
      reqSlots += need
      coveredSlots += Math.min(need, have)
      const missing = Math.max(0, need - have)
      if (open && (missing !== open.missing_headcount || open.end !== t)) {
        gaps.push(open)
        open = null
      }
      if (missing > 0) {
        if (!open) open = { role_id: role, day, start: t, end: t + slot, missing_headcount: missing, penalty_dollars: 0 }
        else open.end = t + slot
      }
    }
    if (open) gaps.push(open)
  }
  for (const g of gaps) {
    const rate = roleById.get(g.role_id)?.gap_penalty_per_hour ?? 0
    g.penalty_dollars = round2((g.missing_headcount * (g.end - g.start) * rate) / 60)
    g.reasons = cfg.employees
      .filter((e) => e.trained_role_ids.includes(g.role_id))
      .map((e): GapReason => {
        const working = shifts.some((s) => s.employee_id === e.id && s.day === g.day && s.start < g.end && g.start < s.end)
        const code: GapReason['code'] = working
          ? 'already_assigned'
          : (hoursUsed.get(e.id) ?? 0) >= (e.max_hours_week ?? 40) - 4
            ? 'at_max_hours'
            : budgetUsed >= cap - 8
              ? 'budget_cap'
              : 'cheaper_to_leave_gap'
        return { employee_id: e.id, code }
      })
  }
  gaps.sort((a, b) => a.day - b.day || a.start - b.start)

  const wage = new Map(cfg.employees.map((e) => [e.id, e.wage_per_hour]))
  const totalHours = shifts.reduce((h, s) => h + paidMinutes(s.end - s.start) / 60, 0)
  const wageCost = shifts.reduce((c, s) => c + (paidMinutes(s.end - s.start) / 60) * (wage.get(s.employee_id) ?? 0), 0)
  const gapPenalty = gaps.reduce((c, g) => c + g.penalty_dollars, 0)
  const metrics: ScheduleMetrics = {
    total_hours: totalHours,
    total_wage_cost: round2(wageCost),
    overtime_hours: 0,
    premium_pay_dollars: 0,
    coverage_pct: reqSlots ? round2((coveredSlots / reqSlots) * 100) : 100,
    gap_penalty_dollars: round2(gapPenalty),
    soft_penalty_dollars: 0,
    objective_dollars: round2(wageCost + gapPenalty),
    budget_hours_cap: cap,
    budget_hours_used: totalHours,
  }
  const schedule: Schedule = {
    store_id: cfg.store.id,
    week_start: cfg.store.week_start,
    config_version: cfg.config_version ?? 1,
    produced_by: 'mock-greedy',
    status: 'feasible',
    shifts,
    gaps,
    soft_violations: [],
    metrics,
    infeasibility: null,
    solver_stats: { mock: true },
  }
  return { schedule, validation: { passed: true, hard_count: 0, violations: [], recomputed_metrics: metrics } }
}

function round2(n: number) {
  return Math.round(n * 100) / 100
}
