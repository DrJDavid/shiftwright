import { useEffect, useMemo, useState } from 'react'
import type { Api } from '../api/client'
import type { Gap, GapReason, GapReasonCode, LawPack, StoreConfig } from '../contracts'
import { fmtDayDate, fmtMoney, fmtRange } from '../lib/format'
import { describeConstraint } from '../lib/ruleNames'

type Props = {
  api: Api
  storeId: string
  gap: Gap
  weekStart: string
  config: StoreConfig
  lawPack: LawPack | null
  onClose: () => void
}

const CODE_LABEL: Record<GapReasonCode, string> = {
  not_trained: 'Not trained for it',
  unavailable: 'Unavailable then',
  at_max_hours: 'Already at max hours',
  budget_cap: 'Would go over the hours budget',
  law_rule: 'Blocked by a labor law',
  minor_rule: 'Blocked by a minor-labor law',
  rest_rule: 'Would break a rest-between-shifts rule',
  already_assigned: 'Working another role then',
  cheaper_to_leave_gap: 'Costs more than leaving the gap',
}

type State = { status: 'loading' } | { status: 'ok'; text: string; reasons: GapReason[] } | { status: 'error'; message: string }

/** Side sheet: why a coverage gap exists. Text and reasons come from POST /gaps/explain (engine reasons). */
export function GapSheet({ api, storeId, gap, weekStart, config, lawPack, onClose }: Props) {
  const [state, setState] = useState<State>({ status: 'loading' })
  const names = useMemo(() => new Map(config.employees.map((e) => [e.id, e.name])), [config.employees])
  const role = config.roles.find((r) => r.id === gap.role_id)
  const lawById = useMemo(() => new Map((lawPack?.rules ?? []).map((r) => [r.id, r])), [lawPack])
  const ruleById = useMemo(() => new Map((config.constraints ?? []).map((c) => [c.id, c])), [config.constraints])

  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    api
      .explainGap(storeId, gap)
      .then((r) => live && setState({ status: 'ok', text: r.text, reasons: r.reasons }))
      .catch((e: Error) => live && setState({ status: 'error', message: e.message }))
    return () => {
      live = false
    }
  }, [api, storeId, gap])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const groups = useMemo(() => {
    if (state.status !== 'ok') return []
    const m = new Map<GapReasonCode, GapReason[]>()
    for (const r of state.reasons) m.set(r.code, [...(m.get(r.code) ?? []), r])
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [state])

  const day = fmtDayDate(weekStart, gap.day)

  return (
    <div className="absolute inset-y-0 right-0 z-40 flex w-[24rem] max-w-full flex-col border-l border-rule bg-panel shadow-xl" role="dialog" aria-label="Why this gap">
      <div className="flex items-start justify-between gap-3 border-b border-rule px-4 py-3">
        <div>
          <div className="text-xs font-semibold tracking-wide text-gap uppercase">Uncovered</div>
          <h3 className="font-semibold">
            {role?.name ?? gap.role_id}, {day.weekday} {fmtRange(gap.start, gap.end)}
          </h3>
          <p className="text-sm text-ink-2">
            {gap.missing_headcount} {gap.missing_headcount === 1 ? 'person' : 'people'} short · {fmtMoney(gap.penalty_dollars)} gap cost
          </p>
        </div>
        <button type="button" onClick={onClose} className="rounded px-2 py-1 text-sm text-muted hover:bg-paper hover:text-ink">
          Close
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 text-sm">
        {state.status === 'loading' && <p className="text-muted">Finding out why…</p>}
        {state.status === 'error' && <p className="text-gap">Couldn't load the explanation: {state.message}</p>}
        {state.status === 'ok' && (
          <>
            <p className="leading-relaxed text-ink-2">{state.text}</p>
            {state.reasons.length > 0 && (
              <div className="mt-4 space-y-3">
                <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">
                  Everyone trained for {role?.name ?? gap.role_id} ({state.reasons.length})
                </h4>
                {groups.map(([code, rs]) => (
                  <div key={code}>
                    <div className="font-medium">
                      {CODE_LABEL[code] ?? code} <span className="font-normal text-muted">· {rs.length}</span>
                    </div>
                    <ul className="mt-1 space-y-0.5">
                      {rs.map((r, i) => {
                        const law = r.law_rule_id ? lawById.get(r.law_rule_id) : undefined
                        const rule = r.constraint_id ? ruleById.get(r.constraint_id) : undefined
                        return (
                          <li key={i} className="text-ink-2">
                            {names.get(r.employee_id) ?? r.employee_id}
                            {law ? (
                              <a href={law.citation.url} target="_blank" rel="noreferrer" className="block text-xs text-pine-dark underline">
                                {law.summary}
                              </a>
                            ) : r.law_rule_id ? (
                              <span className="block text-xs text-muted">{r.law_rule_id}</span>
                            ) : null}
                            {rule && <span className="block text-xs text-muted">{describeConstraint(rule, config)}</span>}
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
