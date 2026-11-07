import { useState } from 'react'
import type { Schedule, ValidationReport } from '../contracts'
import { fmtHours, fmtMoney, fmtPct, fmtRange, WEEKDAY_NAMES } from '../lib/format'

type Props = { schedule: Schedule; validation: ValidationReport | null; employeeName: (id: string) => string }

export function ScheduleStats({ schedule, validation, employeeName }: Props) {
  const m = schedule.metrics
  const [open, setOpen] = useState(false)
  if (!m) return null
  const used = m.budget_hours_used
  const cap = m.budget_hours_cap
  const frac = cap > 0 ? Math.min(1, used / cap) : 0
  const over = used > cap
  // The in-browser mock never runs the real validator; don't let the badge claim it did.
  const mock = schedule.produced_by.startsWith('mock')
  const unchecked = mock || !validation

  return (
    <div className="relative flex items-stretch gap-px border-b border-rule bg-rule">
      <Stat label="Hours used" wide>
        <div className="flex items-baseline gap-1.5">
          <span className="text-xl font-semibold">{fmtHours(used).replace('h', '')}</span>
          <span className="text-sm whitespace-nowrap text-muted">of {fmtHours(cap)}</span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-rule-soft" aria-hidden>
          <div className={`h-full ${over ? 'bg-gap' : 'bg-ink'}`} style={{ width: `${frac * 100}%` }} />
        </div>
      </Stat>
      <Stat label="Wages">
        <span className="text-xl font-semibold">{fmtMoney(m.total_wage_cost)}</span>
      </Stat>
      <Stat label="Coverage">
        <span className="text-xl font-semibold">{fmtPct(m.coverage_pct)}</span>
      </Stat>
      <Stat label="Gap cost">
        <span className={`text-xl font-semibold ${m.gap_penalty_dollars > 0 ? 'text-gap' : ''}`}>
          {fmtMoney(m.gap_penalty_dollars)}
        </span>
      </Stat>
      <div className="flex shrink-0 items-center bg-panel px-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={`rounded-md border px-3 py-2 text-sm font-semibold ${
            unchecked
              ? 'border-warn/40 bg-warn-wash text-warn hover:border-warn'
              : validation.passed
              ? 'border-pine/30 bg-pine-wash text-pine-dark hover:border-pine'
              : 'border-gap/30 bg-gap-wash text-gap hover:border-gap'
          }`}
        >
          {unchecked ? 'Not validated' : validation.hard_count === 0 ? '0 hard violations ✓' : `${validation.hard_count} hard violation${validation.hard_count === 1 ? '' : 's'}`}
        </button>
      </div>
      {open && (
        <div className="absolute top-full right-4 z-30 mt-2 w-[26rem] rounded-lg border border-rule bg-panel p-4 shadow-lg">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="font-semibold">Validator report</h3>
            <button type="button" className="text-sm text-muted hover:text-ink" onClick={() => setOpen(false)}>
              Close
            </button>
          </div>
          {unchecked && (
            <p className="mb-2 text-sm font-medium text-warn">
              {mock
                ? 'This schedule came from the in-browser mock, not the solver. The validator has not checked it.'
                : 'The validator has not checked this schedule. Rebuild to check it.'}
            </p>
          )}
          {validation && !mock && (
            <p className="text-sm text-ink-2">
              The validator re-checks every shift independently of the solver.{' '}
              {validation.passed ? 'This schedule passed.' : 'This schedule did not pass.'}
            </p>
          )}
          {unchecked ? null : validation.violations.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No violations, hard or soft.</p>
          ) : (
            <ul className="mt-2 max-h-64 space-y-1.5 overflow-auto text-sm">
              {validation.violations.map((v, i) => (
                <li key={i} className="flex gap-2">
                  <span className={`shrink-0 font-semibold ${v.severity === 'hard' ? 'text-gap' : 'text-warn'}`}>
                    {v.severity === 'hard' ? 'Hard' : 'Soft'}
                  </span>
                  <span>
                    {v.message}
                    {v.employee_id ? ` (${employeeName(v.employee_id)}` : ''}
                    {v.employee_id && v.day != null ? `, ${WEEKDAY_NAMES[v.day]}` : ''}
                    {v.employee_id && v.start != null && v.end != null ? ` ${fmtRange(v.start, v.end)}` : ''}
                    {v.employee_id ? ')' : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col justify-center bg-panel px-3 py-2.5 ${wide ? 'min-w-36 flex-[1.4]' : 'flex-1'}`}>
      <span className="truncate text-xs text-muted">{label}</span>
      {children}
    </div>
  )
}
