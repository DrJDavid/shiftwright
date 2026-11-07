import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Api } from '../api/client'
import type { OutreachState, SolveResponse } from '../api/protocol'
import type { LawPack, LawRule, ScheduleMetrics, StoreConfig, ValidationReport } from '../contracts'
import { checkRules, describeViolation, type RuleCheck } from '../lib/compliance'
import { fmtDayDate, fmtHours, fmtMoney, fmtPct } from '../lib/format'
import { humanizer } from '../lib/humanize'
import { minorProtections } from '../lib/minors'
import { MinorLine } from './MinorLine'
import { describeConstraint } from '../lib/ruleNames'

type Props = {
  api: Api
  config: StoreConfig
  result: SolveResponse | null
  lawPack: LawPack | null
  onValidated: (v: ValidationReport) => void
}

const COVERAGE: Record<LawPack['coverage'], string> = {
  full: 'Federal, state and city law on file',
  state_only: 'Federal and state law on file; no city file',
  federal_fallback: 'Federal law only; no state file',
}

/** Printable record of what this week's schedule was checked against. Only engine/validator/law-pack/config data. */
export function ReceiptTab({ api, config, result, lawPack, onValidated }: Props) {
  const [validating, setValidating] = useState<string | null>(null)
  const [outreach, setOutreach] = useState<OutreachState | null>(null)
  useEffect(() => {
    api
      .outreach(config.store.id)
      .then(setOutreach)
      .catch(() => setOutreach(null))
  }, [api, config.store.id, result])
  if (!result) {
    return (
      <div className="p-10">
        <h2 className="text-xl font-semibold">No schedule to report on</h2>
        <p className="mt-2 text-ink-2">Build the schedule first. The receipt shows what it was checked against.</p>
      </div>
    )
  }
  const validate = async () => {
    setValidating('Checking…')
    try {
      onValidated(await api.validate(config.store.id, result.schedule))
      setValidating(null)
    } catch (e) {
      setValidating(`Couldn't run the compliance check: ${(e as Error).message}`)
    }
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-paper">
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-rule bg-panel px-4 py-2">
        <span className="text-sm text-ink-2">A printable record of what this week's schedule was checked against.</span>
        {!result.validation && (
          <button type="button" onClick={() => void validate()} className="rounded-md border border-rule px-3 py-1.5 text-sm font-semibold hover:border-ink">
            {validating ?? 'Run the compliance check'}
          </button>
        )}
        <button type="button" onClick={() => window.print()} className="ml-auto rounded-md bg-ink px-3.5 py-1.5 text-sm font-semibold text-white">
          Print / Save PDF
        </button>
      </div>
      <div className="mx-auto my-4 max-w-[52rem] rounded-lg border border-rule bg-panel p-8 shadow-sm">
        <Receipt config={config} result={result} lawPack={lawPack} outreach={outreach} />
      </div>
      {createPortal(
        <div className="sw-print-only">
          <Receipt config={config} result={result} lawPack={lawPack} outreach={outreach} />
        </div>,
        document.body,
      )}
    </div>
  )
}

function Receipt({
  config,
  result,
  lawPack,
  outreach,
}: {
  config: StoreConfig
  result: SolveResponse
  lawPack: LawPack | null
  outreach: OutreachState | null
}) {
  const { schedule, validation } = result
  const rules = useMemo(() => lawPack?.rules ?? [], [lawPack])
  const checks = useMemo(() => checkRules(config, schedule, validation, rules), [config, schedule, validation, rules])
  const j = config.store.jurisdiction
  const place = `${j.city ? `${j.city.replace(/\b\w/g, (c) => c.toUpperCase())}, ` : ''}${j.state}`
  const week = `${fmtDayDate(schedule.week_start, 0).date} – ${fmtDayDate(schedule.week_start, 6).date}, ${schedule.week_start.slice(0, 4)}`
  const stale = (schedule.config_version ?? 0) < (config.config_version ?? 0)
  const hard = (validation?.violations ?? []).filter((v) => v.severity === 'hard')
  const soft = (validation?.violations ?? []).filter((v) => v.severity === 'soft')
  const constraints = (config.constraints ?? []).filter((c) => c.status === 'confirmed')
  const softCost = new Map<string, number>()
  for (const s of schedule.soft_violations ?? []) if (s.constraint_id) softCost.set(s.constraint_id, (softCost.get(s.constraint_id) ?? 0) + s.penalty_dollars)
  const m = validation?.recomputed_metrics

  return (
    <article className="text-[13px] leading-snug text-ink print:text-[11px]">
      <header className="flex items-start justify-between border-b-2 border-ink pb-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-muted uppercase">Compliance receipt</div>
          <h1 className="text-2xl font-bold">{config.store.name}</h1>
          <div className="text-ink-2">
            {place} · Week of {week}
          </div>
        </div>
        <div className="text-right text-xs text-muted">
          <div>Generated {new Date().toLocaleString()}</div>
          <div>
            Schedule by {schedule.produced_by} · settings v{schedule.config_version ?? '?'}
          </div>
          <div>Store id {config.store.id}</div>
        </div>
      </header>

      {stale && <p className="mt-2 text-warn">Settings changed after this schedule was built (v{config.config_version}); rebuild for a current receipt.</p>}

      <section className="mt-4 grid grid-cols-[14rem_1fr] gap-4 break-inside-avoid">
        <div
          className={`rounded-md border-2 p-3 ${!validation ? 'border-warn text-warn' : validation.passed ? 'border-pine text-pine-dark' : 'border-gap text-gap'}`}
        >
          <div className="text-xs font-semibold tracking-wide uppercase">Independent compliance check</div>
          <div className="text-xl font-bold">{!validation ? 'Not run' : validation.passed ? 'Passed' : 'Did not pass'}</div>
          {validation && (
            <div className="text-sm">
              {plural(validation.hard_count, 'hard violation')} · {plural(soft.length, 'soft cost')}
            </div>
          )}
          <p className="mt-1 text-xs text-ink-2">Re-checks every shift against the labor rules and store rules, separately from the scheduler.</p>
        </div>
        <MetricsTable claimed={schedule.metrics ?? null} recomputed={m ?? null} />
      </section>

      {hard.length > 0 && (
        <section className="mt-4 break-inside-avoid">
          <H>Hard violations</H>
          <ul className="list-disc pl-5 text-gap">
            {hard.map((v, i) => (
              <li key={i}>{describeViolation(v, config)}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-5">
        <H>
          Labor law · {place}
          {lawPack && <span className="ml-2 font-normal normal-case text-muted">{COVERAGE[lawPack.coverage]}</span>}
        </H>
        {!lawPack && <p className="text-warn">Law pack not loaded, so no law rules are listed.</p>}
        {(lawPack?.warnings ?? []).map((w, i) => (
          <p key={i} className="text-warn">
            {w}
          </p>
        ))}
        <div className="divide-y divide-rule-soft">
          {checks
            .filter((c) => c.applies && !(c.quiet && c.violations.length === 0))
            .map((c) => (
              <RuleBlock key={c.rule.id} c={c} config={config} />
            ))}
        </div>
        {checks.some((c) => !c.applies || (c.quiet && c.violations.length === 0)) && (
          <div className="mt-2 break-inside-avoid">
            <div className="text-xs font-semibold text-muted">Also checked, nothing in this schedule triggers them</div>
            <ul className="mt-0.5 space-y-0.5 text-[11px] text-ink-2">
              {checks
                .filter((c) => !c.applies || (c.quiet && c.violations.length === 0))
                .map((c) => (
                  <li key={c.rule.id}>
                    <span className="font-medium">{c.rule.summary}</span>{' '}
                    <span className="text-muted">
                      — {c.applies ? c.quiet : c.notApplicable}{' '}
                      <a href={c.rule.citation.url} className="underline">
                        {c.rule.citation.title}
                      </a>
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </section>

      <MinorsSection config={config} schedule={schedule} rules={rules} />

      <section className="mt-5 break-inside-avoid">
        <H>Store rules</H>
        <table className="w-full">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-1 pr-2 font-medium">Rule</th>
              <th className="py-1 pr-2 font-medium">Type</th>
              <th className="py-1 pr-2 font-medium">From</th>
              <th className="py-1 text-right font-medium">Cost this week</th>
            </tr>
          </thead>
          <tbody>
            {constraints.map((c) => {
              const vs = (validation?.violations ?? []).filter((v) => v.constraint_id === c.id)
              return (
                <tr key={c.id} className="border-t border-rule-soft align-top">
                  <td className="py-1 pr-2">{describeConstraint(c, config)}</td>
                  <td className="py-1 pr-2 whitespace-nowrap">
                    {c.strength === 'hard' ? 'Hard' : `Soft, ${fmtMoney(c.weight_dollars ?? 0)}`}
                  </td>
                  <td className="py-1 pr-2 capitalize">{c.source}</td>
                  <td className="py-1 text-right whitespace-nowrap tabular-nums">
                    {c.strength === 'hard'
                      ? vs.length
                        ? <span className="text-gap">{plural(vs.length, 'violation')}</span>
                        : 'Met'
                      : softCost.has(c.id)
                        ? fmtMoney(softCost.get(c.id)!, { cents: true })
                        : vs.length
                          ? plural(vs.length, 'item')
                          : '$0'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {softCost.size === 0 && soft.length > 0 && (
          <p className="mt-1 text-xs text-muted">Per-rule soft costs come from the scheduler's soft violations; this schedule lists none, so soft items are counted from the compliance check.</p>
        )}
      </section>

      <section className="mt-5 break-inside-avoid">
        <H>Premium pay and overtime</H>
        {m ? (
          <p>
            Premium pay {fmtMoney(m.premium_pay_dollars ?? 0, { cents: true })} · overtime {fmtHours(m.overtime_hours)} (compliance check, included in wage cost{' '}
            {fmtMoney(m.total_wage_cost)}).
          </p>
        ) : (
          <p className="text-warn">Run the compliance check to report premiums.</p>
        )}
        <p className="text-xs text-muted">Premiums are reported as a weekly total; an itemised list by rule and employee isn't available from the server yet.</p>
      </section>

      <CallOutRepairs config={config} outreach={outreach} />

      <footer className="mt-6 border-t border-rule pt-2 text-[11px] text-muted">
        Every number here comes from the compliance check's recomputation, the store's settings, or a direct count of the schedule's shifts. Law text and
        links come from the labor rules on file; check the linked sources before relying on them.
      </footer>
    </article>
  )
}

function RuleBlock({ c, config }: { c: RuleCheck; config: StoreConfig }) {
  const r = c.rule
  const level = r.level === 'city' ? (r.jurisdiction.city ?? 'City') : r.level === 'federal' ? 'Federal' : r.jurisdiction.state
  return (
    <div className="grid grid-cols-[1fr_15rem] gap-4 py-2.5 break-inside-avoid">
      <div>
        <div className="flex items-baseline gap-2">
          <span className="rounded bg-rule-soft px-1 text-[10px] font-semibold uppercase">{level}</span>
          <span className="font-semibold">{r.summary}</span>
        </div>
        <div className="mt-0.5 text-xs text-ink-2">
          <a href={r.citation.url} className="underline">
            {r.citation.title}
          </a>{' '}
          <span className="text-muted break-all print:inline">({r.citation.url})</span>
        </div>
        {r.citation.excerpt && <p className="mt-0.5 text-xs text-muted italic">"{r.citation.excerpt}"</p>}
        <div className="mt-0.5 text-[11px] text-muted">
          Last verified {r.citation.last_verified} · confidence {r.confidence}
          {r.verified === false ? ' · not yet verified by a person' : ''}
        </div>
      </div>
      <div className="text-xs">
        {!c.applies ? (
          <p className="text-muted">Not applicable: {c.notApplicable}</p>
        ) : (
          <>
            <div className={`font-semibold ${c.violations.some((v) => v.severity === 'hard') ? 'text-gap' : c.unchecked ? 'text-muted' : 'text-pine-dark'}`}>
              {c.violations.length ? plural(c.violations.length, 'violation') : c.unchecked ? 'Not checked' : 'No violations'}
            </div>
            <ul className="mt-0.5 space-y-0.5 text-ink-2">
              {c.facts.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
              {c.violations.slice(0, 4).map((v, i) => (
                <li key={`v${i}`} className="text-gap">
                  {describeViolation(v, config)}
                </li>
              ))}
              {c.violations.length > 4 && <li className="text-gap">…and {c.violations.length - 4} more</li>}
              {c.unchecked && <li className="text-muted">{c.unchecked}</li>}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}

function MetricsTable({ claimed, recomputed }: { claimed: ScheduleMetrics | null; recomputed: ScheduleMetrics | null }) {
  const rows: [string, (x: ScheduleMetrics) => string][] = [
    ['Paid hours', (x) => `${fmtHours(x.budget_hours_used)} of ${fmtHours(x.budget_hours_cap)} cap`],
    ['Wage cost (incl. overtime)', (x) => fmtMoney(x.total_wage_cost)],
    ['Overtime hours', (x) => fmtHours(x.overtime_hours)],
    ['Premium pay', (x) => fmtMoney(x.premium_pay_dollars ?? 0, { cents: true })],
    ['Coverage', (x) => fmtPct(x.coverage_pct)],
    ['Uncovered (gap) cost', (x) => fmtMoney(x.gap_penalty_dollars)],
    ['Soft-rule cost', (x) => fmtMoney(x.soft_penalty_dollars)],
  ]
  return (
    <table className="w-full self-start">
      <thead>
        <tr className="text-left text-xs text-muted">
          <th className="py-0.5 font-medium" />
          <th className="py-0.5 text-right font-medium">Scheduler reported</th>
          <th className="py-0.5 text-right font-medium">Compliance check</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, f]) => {
          const a = claimed ? f(claimed) : '—'
          const b = recomputed ? f(recomputed) : '—'
          return (
            <tr key={label} className="border-t border-rule-soft">
              <td className="py-0.5 text-ink-2">{label}</td>
              <td className="py-0.5 text-right tabular-nums">{a}</td>
              <td className={`py-0.5 text-right tabular-nums ${recomputed && a !== b ? 'font-semibold text-warn' : ''}`}>{b}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Call-ins accepted through outreach this week, with each person's premium from the server (premium.by_employee). */
function CallOutRepairs({ config, outreach }: { config: StoreConfig; outreach: OutreachState | null }) {
  const accepted = outreach?.accepted_employee_ids ?? []
  if (!outreach || accepted.length === 0) return null
  const h = humanizer(config)
  const name = (id: string) => config.employees.find((e) => e.id === id)?.name ?? id
  const by = new Map((outreach.premium?.by_employee ?? []).map((b) => [b.employee_id, b]))
  const total = accepted.reduce((c, id) => c + (by.get(id)?.premium_pay_dollars ?? 0), 0)
  const notes = new Set(accepted.map((id) => by.get(id)?.note ?? ''))
  const shared = notes.size === 1 ? [...notes][0] : null
  return (
    <section className="mt-5 break-inside-avoid">
      <H>Call-out repairs</H>
      <p className="mb-1 text-ink-2">
        {accepted.length} {accepted.length === 1 ? 'call-in' : 'call-ins'} accepted by text
        {outreach.mode === 'group_offer' ? ' (group offer)' : ''}. Predictive-scheduling pay:{' '}
        <span className="font-semibold">
          {outreach.premium?.status === 'owed' ? fmtMoney(total, { cents: true }) + ' owed' : outreach.premium?.status === 'exempt' ? 'none owed (exempt)' : 'not applicable'}
        </span>
        .
      </p>
      {outreach.premium?.note && <p className="mb-1 text-xs text-muted">{h(outreach.premium.note)}</p>}
      {shared && <p className="mb-1 text-xs text-ink-2">Basis for each: {h(shared)}</p>}
      <table className="w-full">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-1 pr-2 font-medium">Employee</th>
            <th className="py-1 pr-2 text-right font-medium">Premium</th>
            <th className="py-1 font-medium">Basis</th>
          </tr>
        </thead>
        <tbody>
          {accepted.map((id) => {
            const b = by.get(id)
            return (
              <tr key={id} className="border-t border-rule-soft align-top">
                <td className="py-1 pr-2">{name(id)}</td>
                <td className="py-1 pr-2 text-right tabular-nums">{b ? fmtMoney(b.premium_pay_dollars, { cents: true }) : '—'}</td>
                <td className="py-1 text-xs text-ink-2">{b ? (shared ? 'As above' : h(b.note)) : 'Not reported by the server'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

/** Minor protection made visible even when nothing is violated (from config + law pack + schedule only). */
function MinorsSection({ config, schedule, rules }: { config: StoreConfig; schedule: SolveResponse['schedule']; rules: LawRule[] }) {
  const list = minorProtections(config, schedule, rules)
  if (list.length === 0) return null
  return (
    <section className="mt-5 break-inside-avoid">
      <H>Minors kept off hazardous roles</H>
      <ul className="space-y-1.5">
        {list.map((m) => (
          <li key={m.employee.id}>
            <MinorLine m={m} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-1.5 border-b border-rule pb-0.5 text-xs font-bold tracking-wide text-ink uppercase">{children}</h2>
}

function plural(n: number, one: string) {
  return `${n} ${n === 1 ? one : `${one}s`}`
}
