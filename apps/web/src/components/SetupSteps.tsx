import type { ReactNode } from 'react'
import type { Readiness } from '../api/protocol'
import { setupSteps, type Check, type StepState } from '../lib/setupSteps'
import { EquipmentReview } from './EquipmentReview'
import { SolveButton, type SolveState } from './SolveButton'

type Props = {
  readiness: Readiness | null
  error: string | null
  solve: SolveState
  onBuild: () => void
  roles: { id: string; name: string }[]
  onEquipment: (roleId: string, decision: 'confirm' | 'reject') => Promise<void>
  /** Swaps rule ids and tag ids in check details for plain words (lib/ruleNames). */
  plain?: (text: string) => string
  /** "Chicago, IL": the resolved-law check reads "Labor rules for Chicago, IL". */
  place: string
}

/** Without these the build has nobody to place or nothing to cover (PUNCHLIST B4 QA), so Build stays off. */
const BUILD_NEEDS: [id: string, what: string][] = [
  ['employees', 'your team'],
  ['training', 'who can work each role'],
  ['demand', 'how many people you need, and when'],
]

function listPhrase(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** Setup mode's left rail: Business → Hours & budget → Team → Staffing → Rules → Build. */
export function SetupSteps({ readiness, error, solve, onBuild, roles, onEquipment, plain = (t) => t, place }: Props) {
  const steps = setupSteps(readiness)
  const detail = (c: Check) => (c.id === 'jurisdiction' && c.ok ? `Labor rules for ${place}` : plain(c.detail))
  const current = steps.find((s) => !s.done)?.id
  const ready = readiness?.ready ?? false
  const missing = readiness ? BUILD_NEEDS.filter(([id]) => !readiness.checks.find((c) => c.id === id)?.ok).map(([, what]) => what) : []
  const equipment = readiness?.checks.find((c) => c.id === 'equipment_roles')

  return (
    <aside className="flex min-h-0 flex-col border-r border-rule bg-panel" aria-label="Setup steps">
      <div className="px-4 pt-4 pb-2">
        <h2 className="font-semibold">Set up your workplace</h2>
        <p className="mt-0.5 text-xs text-muted">The chat walks you through each step.</p>
      </div>
      <ol className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {steps.map((s, i) => (
          <Step key={s.id} n={i + 1} step={s} current={s.id === current} detail={detail}>
            {s.id === 'team' && <EquipmentReview check={equipment} roles={roles} onDecide={onEquipment} />}
          </Step>
        ))}
        <li className="flex gap-3 px-2 py-2">
          <Dot n={steps.length + 1} state={ready ? 'current' : 'todo'} />
          <span className={`text-sm font-semibold ${ready ? 'text-ink' : 'text-muted'}`}>Build</span>
        </li>
      </ol>
      <div className="shrink-0 border-t border-rule px-4 py-3">
        {error && <p className="mb-2 text-xs text-gap">Couldn't check setup: {error}</p>}
        {!readiness && !error && <p className="mb-2 text-xs text-muted">Checking…</p>}
        {ready ? (
          <SolveButton state={solve} onSolve={onBuild} label="Build my schedule" />
        ) : (
          <>
            <SolveButton state={solve} onSolve={onBuild} label="Build my schedule" disabled />
            {readiness && missing.length > 0 ? (
              <p className="mt-2 text-xs text-muted">To build a schedule, first add {listPhrase(missing)}.</p>
            ) : readiness && solve.status !== 'running' && (
              <p className="mt-2 text-xs text-muted">
                Some steps aren't done, so parts of the week may go uncovered.{' '}
                <button type="button" onClick={onBuild} className="font-semibold text-ink underline">
                  Build anyway
                </button>
              </p>
            )}
          </>
        )}
      </div>
    </aside>
  )
}

function Dot({ n, state }: { n: number; state: 'done' | 'current' | 'todo' | 'attention' }) {
  const cls =
    state === 'done'
      ? 'bg-pine text-white'
      : state === 'attention'
        ? 'bg-warn-wash text-warn ring-1 ring-warn/40'
        : state === 'current'
          ? 'bg-ink text-white'
          : 'border border-rule text-muted'
  return (
    <span className={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${cls}`} aria-hidden>
      {state === 'done' ? '✓' : state === 'attention' ? '!' : n}
    </span>
  )
}

function Step({
  n,
  step,
  current,
  detail,
  children,
}: {
  n: number
  step: StepState
  current: boolean
  detail: (c: Check) => string
  children?: ReactNode
}) {
  const state = step.done ? (step.attention ? 'attention' : 'done') : current ? 'current' : 'todo'
  const open = step.checks.filter((c) => !c.ok)
  return (
    <li className="group relative">
      <div
        tabIndex={0}
        className="flex gap-3 rounded-md px-2 py-2 outline-none hover:bg-paper focus-visible:bg-paper"
        aria-label={`${step.label}: ${step.done ? 'done' : 'not done'}`}
      >
        <Dot n={n} state={state} />
        <div className="min-w-0">
          <span className={`block text-sm font-semibold ${step.done || current ? 'text-ink' : 'text-ink-2'}`}>{step.label}</span>
          {current && open[0] && <span className="block text-xs text-ink-2">{detail(open[0])}</span>}
          {children && <div className="mt-1">{children}</div>}
        </div>
      </div>
      {step.checks.length > 0 && (
        <div
          role="tooltip"
          className="pointer-events-none invisible absolute top-0 left-full z-40 ml-2 w-72 rounded-md border border-rule bg-panel px-3 py-2 text-sm opacity-0 shadow-lg transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
        >
          <ul className="space-y-1.5">
            {step.checks.map((c) => (
              <li key={c.id} className="flex gap-2">
                <span className={c.ok ? (c.severity === 'warn' ? 'text-warn' : 'text-pine') : 'text-muted'} aria-hidden>
                  {c.ok ? (c.severity === 'warn' ? '!' : '✓') : '○'}
                </span>
                <span>
                  <span className="font-medium">{c.label}</span>
                  {c.detail && <span className="block text-xs text-ink-2">{detail(c)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  )
}
