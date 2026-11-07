// Facts for the compliance receipt. Every line is either read from the validator report / law pack /
// config, or counted directly from the schedule's shifts (labelled as such). No thresholds or amounts
// are invented: limits come from each law rule's own params.
import type { Employee, LawRule, Schedule, Shift, StoreConfig, ValidationReport, Violation } from '../contracts'
import { fmtHours, fmtMoney, fmtRange, fmtTime, WEEKDAY_NAMES } from './format'
import { shiftWage, tagLabel } from './vocab'

export type RuleCheck = {
  rule: LawRule
  applies: boolean
  /** Why it doesn't apply, when it doesn't. */
  notApplicable?: string
  facts: string[]
  violations: Violation[]
  /** The validator doesn't check this rule type (SEMANTICS #14). */
  unchecked?: string
}

const CODE_FOR: Partial<Record<LawRule['type'], Violation['code'][]>> = {
  weekly_overtime: ['overtime_not_allowed'],
  daily_overtime: ['overtime_not_allowed'],
  meal_break: ['meal_break'],
  rest_break: ['rest_break'],
  minor_limits: ['minor_hours'],
  minor_prohibited_roles: ['minor_prohibited_role'],
  min_rest_between_shifts: ['rest_between_shifts'],
  minimum_wage: ['below_minimum_wage'],
}

export function paidMinutes(s: Shift): number {
  return s.end - s.start - (s.breaks ?? []).filter((b) => !b.paid).reduce((m, b) => m + b.end - b.start, 0)
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export function checkRules(config: StoreConfig, schedule: Schedule, validation: ValidationReport | null, rules: LawRule[]): RuleCheck[] {
  const shifts = schedule.shifts ?? []
  const emp = new Map(config.employees.map((e) => [e.id, e]))
  const byEmp = new Map<string, Shift[]>()
  for (const s of shifts) byEmp.set(s.employee_id, [...(byEmp.get(s.employee_id) ?? []), s])
  const weekHours = (id: string) => (byEmp.get(id) ?? []).reduce((m, s) => m + paidMinutes(s), 0) / 60
  const scheduled = [...byEmp.keys()].map((id) => emp.get(id)).filter((e): e is Employee => !!e)
  const name = (id: string) => emp.get(id)?.name ?? id
  const sw = config.store.school_week ?? null

  return rules.map((rule): RuleCheck => {
    const p = (rule.params ?? {}) as Record<string, unknown>
    // By law_rule_id; violations the validator didn't attribute to a rule match by code.
    const violations = (validation?.violations ?? []).filter(
      (v) => v.law_rule_id === rule.id || (!v.law_rule_id && (CODE_FOR[rule.type] ?? []).includes(v.code)),
    )
    const out: RuleCheck = { rule, applies: true, facts: [], violations }
    const f = out.facts
    switch (rule.type) {
      case 'weekly_overtime': {
        const t = num(p.threshold_hours)
        const over = t == null ? [] : scheduled.filter((e) => weekHours(e.id) > t)
        const max = Math.max(0, ...scheduled.map((e) => weekHours(e.id)))
        f.push(`Most hours for one person this week: ${fmtHours(max)}${t != null ? ` (threshold ${fmtHours(t)})` : ''}.`)
        f.push(over.length ? `Over the threshold: ${over.map((e) => `${e.name} ${fmtHours(weekHours(e.id))}`).join(', ')}.` : 'Nobody is over the threshold.')
        if (validation) f.push(`Validator's overtime hours: ${fmtHours(validation.recomputed_metrics.overtime_hours)}.`)
        break
      }
      case 'daily_overtime': {
        const t = num(p.threshold_hours)
        const max = Math.max(0, ...shifts.map((s) => paidMinutes(s) / 60))
        f.push(`Longest paid day: ${fmtHours(max)}${t != null ? ` (threshold ${fmtHours(t)})` : ''}.`)
        if (validation) f.push(`Validator's overtime hours: ${fmtHours(validation.recomputed_metrics.overtime_hours)}.`)
        break
      }
      case 'meal_break':
      case 'rest_break': {
        const kind = rule.type === 'meal_break' ? 'meal' : 'rest'
        const after = num(rule.type === 'meal_break' ? p.after_minutes : p.per_minutes_worked)
        const long = after == null ? [] : shifts.filter((s) => s.end - s.start > after)
        const withBreak = long.filter((s) => (s.breaks ?? []).some((b) => b.kind === kind))
        f.push(
          after == null
            ? `${plural(shifts.length, 'shift')} scheduled.`
            : `${plural(long.length, 'shift')} longer than ${fmtHours(after / 60)}; ${withBreak.length} of them have a ${kind} break.`,
        )
        break
      }
      case 'minor_limits': {
        const ruleSw = p.school_week
        if (sw !== null && typeof ruleSw === 'boolean' && ruleSw !== sw) {
          out.applies = false
          out.notApplicable = `This week is marked ${sw ? 'a school week' : 'not a school week'}; this rule is for ${ruleSw ? 'school weeks' : 'non-school weeks'}.`
          break
        }
        const lo = num(p.age_min) ?? 0
        const hi = num(p.age_max) ?? 17
        const minors = scheduled.filter((e) => e.age >= lo && e.age <= hi)
        if (minors.length === 0) {
          f.push(`No one aged ${lo}–${hi} is scheduled.`)
          break
        }
        const dayMax = Math.max(...minors.flatMap((e) => (byEmp.get(e.id) ?? []).map((s) => paidMinutes(s) / 60)))
        const weekMax = Math.max(...minors.map((e) => weekHours(e.id)))
        const earliest = Math.min(...minors.flatMap((e) => (byEmp.get(e.id) ?? []).map((s) => s.start)))
        const latest = Math.max(...minors.flatMap((e) => (byEmp.get(e.id) ?? []).map((s) => s.end)))
        f.push(`${plural(minors.length, 'employee')} aged ${lo}–${hi} scheduled: ${minors.map((e) => `${e.name} (${e.age})`).join(', ')}.`)
        const dl = num(p.max_hours_day)
        const wl = num(p.max_hours_week)
        f.push(`Longest day ${fmtHours(dayMax)}${dl != null ? ` vs ${fmtHours(dl)} limit` : ''}; most in a week ${fmtHours(weekMax)}${wl != null ? ` vs ${fmtHours(wl)} limit` : ''}.`)
        const es = num(p.earliest_start)
        const le = num(p.latest_end)
        f.push(`Earliest start ${fmtTime(earliest)}${es != null ? ` (not before ${fmtTime(es)})` : ''}; latest end ${fmtTime(latest)}${le != null ? ` (not after ${fmtTime(le)})` : ''}.`)
        if (sw === null) f.push('School week not set, so school-week and non-school-week limits are both enforced (strictest).')
        break
      }
      case 'minor_prohibited_roles': {
        const below = num(p.age_below) ?? 18
        const floor = num(p.age_min) // v1.5: optional lower bound (SEMANTICS #21)
        const tags = Array.isArray(p.role_tags) ? (p.role_tags as string[]) : []
        const roleTags = (config.role_tags ?? {}) as Record<string, string[]>
        const banned = Object.entries(roleTags)
          .filter(([, ts]) => ts.some((t) => tags.includes(t)))
          .map(([r]) => r)
        const inBand = (age: number) => age < below && (floor == null || age >= floor)
        const young = scheduled.filter((e) => inBand(e.age))
        const hits = shifts.filter((s) => inBand(emp.get(s.employee_id)?.age ?? 99) && s.segments.some((g) => banned.includes(g.role_id)))
        const roleNames = banned.map((r) => config.roles.find((x) => x.id === r)?.name ?? r)
        const band = floor != null ? `aged ${floor}–${below - 1}` : `under ${below}`
        f.push(`${plural(young.length, 'employee')} ${band} scheduled; ${roleNames.length ? roleNames.join(', ') : 'no roles'} tagged ${tags.map(tagLabel).join(', ') || '—'}.`)
        f.push(hits.length ? `Shifts by employees ${floor != null ? `aged ${floor}–${below - 1}` : `under ${below}`} in those roles: ${hits.map((s) => `${name(s.employee_id)} ${WEEKDAY_NAMES[s.day]}`).join(', ')}.` : `No one ${floor != null ? `aged ${floor}–${below - 1}` : `under ${below}`} works those roles.`)
        break
      }
      case 'min_rest_between_shifts': {
        const need = num(p.minutes)
        let minRest = Infinity
        let who = ''
        for (const [id, ss] of byEmp) {
          const sorted = [...ss].sort((a, b) => a.day * 1440 + a.start - (b.day * 1440 + b.start))
          for (let i = 1; i < sorted.length; i++) {
            const gap = sorted[i].day * 1440 + sorted[i].start - (sorted[i - 1].day * 1440 + sorted[i - 1].end)
            if (gap < minRest) {
              minRest = gap
              who = `${name(id)}, ${WEEKDAY_NAMES[sorted[i - 1].day]}→${WEEKDAY_NAMES[sorted[i].day]}`
            }
          }
        }
        f.push(
          Number.isFinite(minRest)
            ? `Shortest rest between two shifts: ${fmtHours(minRest / 60)} (${who})${need != null ? `; rule asks for ${fmtHours(need / 60)}` : ''}.`
            : 'Nobody works two shifts this week.',
        )
        if (num(p.premium_multiplier) && validation)
          f.push(`Priced, not forbidden: premium pay recomputed by the validator ${fmtMoney(validation.recomputed_metrics.premium_pay_dollars ?? 0, { cents: true })}.`)
        break
      }
      case 'minimum_wage': {
        const min = num(p.dollars_per_hour)
        const lowest = scheduled.reduce<Employee | null>((a, e) => (!a || e.wage_per_hour < a.wage_per_hour ? e : a), null)
        const below = min == null ? [] : scheduled.filter((e) => e.wage_per_hour < min)
        if (lowest) f.push(`Lowest wage scheduled: ${fmtMoney(lowest.wage_per_hour, { cents: true })} (${lowest.name})${min != null ? `; minimum ${fmtMoney(min, { cents: true })}` : ''}.`)
        if (below.length) f.push(`Below the minimum: ${below.map((e) => e.name).join(', ')}.`)
        break
      }
      case 'tipped_minimum_wage': {
        // SEMANTICS #15/#20: a shift is tipped iff every segment is a tipped role and the employee has a tipped wage.
        const cash = num(p.cash_wage_per_hour)
        const roleById = new Map(config.roles.map((r) => [r.id, r]))
        const tippedEmps = scheduled.filter((e) => (byEmp.get(e.id) ?? []).some((s) => shiftWage(s, e, roleById).tipped))
        if (tippedEmps.length === 0) {
          f.push('No shifts this week are paid at a tipped wage.')
          break
        }
        const low = tippedEmps.reduce((a, e) => (e.tipped_wage_per_hour! < a.tipped_wage_per_hour! ? e : a))
        f.push(`${plural(tippedEmps.length, 'employee')} with tipped shifts; lowest tipped cash wage ${fmtMoney(low.tipped_wage_per_hour!, { cents: true })} (${low.name})${cash != null ? ` vs ${fmtMoney(cash, { cents: true })} required` : ''}.`)
        f.push('Tips are never counted toward cost or pay here.')
        break
      }
      case 'predictive_scheduling': {
        const over = num(p.applies_if_employees_over)
        const count = config.store.employer_employee_count ?? null
        if (over != null && count != null && count <= over) {
          out.applies = false
          out.notApplicable = `Employer has ${count} employees; the rule applies above ${over}.`
          break
        }
        f.push(
          `Applies to changes made after the schedule is posted${num(p.notice_days) != null ? ` (${p.notice_days} days' notice)` : ''}. This is the posted schedule; premiums for later changes are priced in Fix call-outs.`,
        )
        if (count == null) f.push('Employer size not set, so the rule is assumed to apply.')
        out.unchecked = 'Change premiums are checked on fix plans, not on the posted week (SEMANTICS #14, #17).'
        break
      }
      case 'reporting_time_pay':
        out.unchecked = 'Not checked by the validator (SEMANTICS #14).'
        break
    }
    return out
  })
}

export function describeViolation(v: Violation, config: StoreConfig): string {
  const who = v.employee_id ? config.employees.find((e) => e.id === v.employee_id)?.name ?? v.employee_id : ''
  const when = v.day != null ? ` ${WEEKDAY_NAMES[v.day]}${v.start != null && v.end != null ? ` ${fmtRange(v.start, v.end)}` : ''}` : ''
  return `${v.message}${who ? ` (${who}${when})` : when ? ` (${when.trim()})` : ''}`
}
