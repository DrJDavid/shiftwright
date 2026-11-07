import { useState } from 'react'
import type { Schedule, ValidationReport } from '../contracts'
import { fmtHours, fmtMoney, fmtPct, fmtRange, WEEKDAY_NAMES } from '../lib/format'

type Props = { schedule: Schedule; validation: ValidationReport; employeeName: (id: string) => string }

export function ScheduleStats({ schedule, validation, employeeName }: Props) {
  const m = schedule.metrics
  const [open, setOpen] = useState(false)
  if (!m) return null
  const used = m.budget_hours_used
  const cap = m.budget_hours_cap
  const frac = cap > 0 ? Math.min(1, used / cap) : 0
  const over = used > cap

  return (
    <div className="relative flex items-stretch gap-px border-b border-rule bg-rule">
      <Stat label="Hours used" wide>
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-semibold">{fmtHours(used).replace('h', '')}</span>
          <span className="text-sm text-muted">of {fmtHours(cap)} cap</span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-rule-soft" aria-hidden>
          <div className={`h-full ${over ? 'bg-gap' : 'bg-ink'}`} style={{ width: `${frac * 100}%` }} />
        </div>
      </Stat>
      <Stat label="Wage cost">
        <span className="text-2xl font-semibold">{fmtMoney(m.total_wage_cost)}</span>
      </Stat>
      <Stat label="Coverage">
        <span className="text-2xl font-semibold">{fmtPct(m.coverage_pct)}</span>
      </Stat>
      <Stat label="Uncovered cost">
        <span className={`text-2xl font-semibold ${m.gap_penalty_dollars > 0 ? 'text-gap' : ''}`}>
          {fmtMoney(m.gap_penalty_dollars)}
        </span>
      </Stat>
      <div className="flex items-center bg-panel px-4">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={`rounded-md border px-3 py-2 text-sm font-semibold ${
            validation.passed
              ? 'border-pine/30 bg-pine-wash text-pine-dark hover:border-pine'
              : 'border-gap/30 bg-gap-wash text-gap hover:border-gap'
          }`}
        >
          {validation.hard_count === 0 ? '0 hard violations ✓' : `${validation.hard_count} hard violations`}
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
          <p className="text-sm text-ink-2">
            The validator re-checks every shift independently of the solver.{' '}
            {validation.passed ? 'This schedule passed.' : 'This schedule did not pass.'}
          </p>
          {validation.violations.length === 0 ? (
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
    <div className={`flex flex-col justify-center bg-panel px-4 py-2.5 ${wide ? 'min-w-56 flex-[1.4]' : 'flex-1'}`}>
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  )
}
