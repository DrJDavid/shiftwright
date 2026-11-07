import { useState, type ReactNode } from 'react'
import type { Readiness } from '../api/protocol'
import { SolveButton, type SolveState } from './SolveButton'

type Props = {
  readiness: Readiness | null
  error: string | null
  solve: SolveState
  onSolve: () => void
  open: boolean
  onToggle: () => void
  /** The rule list (Rulebook), shown under the checklist. */
  children?: ReactNode
  /** v1.4: roles tagged as powered equipment automatically, for the leader to confirm or reject. */
  roles?: { id: string; name: string }[]
  onEquipment?: (roleId: string, decision: 'confirm' | 'reject') => Promise<void>
}

/** Role names the server tagged automatically, read from the equipment_roles check's detail. */
function autoTagged(detail: string, roles: { id: string; name: string }[]) {
  const m = detail.match(/:\s*(.+?)\.\s*Please confirm/)
  if (!m) return []
  return m[1]
    .split(', ')
    .map((n) => roles.find((r) => r.name === n.trim()))
    .filter((r): r is { id: string; name: string } => !!r)
}

/** Rulebook pane: readiness meter + checklist, the rule list, and Build schedule. */
export function ReadinessRail({ readiness, error, solve, onSolve, open, onToggle, children, roles = [], onEquipment }: Props) {
  const [deciding, setDeciding] = useState<string | null>(null)
  // null = automatic: checklist open until everything is ready.
  const [listOpen, setListOpen] = useState<boolean | null>(null)
  const showList = listOpen ?? !readiness?.ready
  const done = readiness?.checks.filter((c) => c.ok).length ?? 0
  const total = readiness?.checks.length ?? 0
  if (!open) {
    return (
      <aside className="flex min-h-0 flex-col items-center border-l border-rule bg-panel py-3" aria-label="Rulebook">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={false}
          className="flex flex-col items-center gap-2 rounded-md px-1.5 py-2 text-sm font-semibold text-ink-2 hover:bg-paper hover:text-ink"
        >
          <span className="[writing-mode:vertical-rl]">Rulebook</span>
          {readiness && (
            <span className={`text-xs ${readiness.ready ? 'text-pine' : 'text-muted'}`}>
              {done}/{total}
            </span>
          )}
        </button>
      </aside>
    )
  }
  return (
    <aside className="flex min-h-0 flex-col border-l border-rule bg-panel" aria-label="Rulebook">
      <div className="shrink-0 border-b border-rule px-4 py-3">
        <div className="flex items-baseline justify-between">
          <h2 className="font-semibold">Ready to build</h2>
          <span className="flex items-baseline gap-3">
            {readiness && (
              <span className={`text-sm ${readiness.ready ? 'text-pine' : 'text-muted'}`}>
                {done} of {total}
              </span>
            )}
            <button type="button" onClick={onToggle} aria-expanded className="text-sm text-muted hover:text-ink">
              Hide
            </button>
          </span>
        </div>
        {readiness && (
          <button
            type="button"
            onClick={() => setListOpen(!showList)}
            aria-expanded={showList}
            className="mt-2 flex w-full items-center gap-2"
            title={showList ? 'Hide checklist' : 'Show checklist'}
          >
            <span className="flex flex-1 gap-1" aria-hidden>
              {readiness.checks.map((c) => (
                <span key={c.id} className={`h-1.5 flex-1 rounded-full ${c.ok ? 'bg-pine' : 'bg-rule'}`} />
              ))}
            </span>
            <span className="text-xs text-muted">{showList ? '▴' : '▾'}</span>
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {error && <p className="text-sm text-gap">Couldn't load readiness: {error}</p>}
        {!readiness && !error && <p className="text-sm text-muted">Checking…</p>}
        <ul className={`space-y-2.5 ${showList ? 'mb-4 border-b border-rule pb-4' : 'hidden'}`}>
          {readiness?.checks.map((c) => (
            <li key={c.id} className="flex gap-2.5 text-sm">
              <span
                className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                  c.ok ? 'bg-pine text-white' : 'border border-muted text-transparent'
                }`}
                aria-label={c.ok ? 'Done' : 'Not done'}
              >
                ✓
              </span>
              <span>
                <span className={c.ok ? 'text-ink' : 'font-medium text-ink'}>{c.label}</span>
                {c.detail && <span className="block text-xs text-muted">{c.detail}</span>}
                {c.id === 'equipment_roles' && onEquipment && autoTagged(c.detail, roles).length > 0 && (
                  <span className="mt-1 block space-y-1">
                    {autoTagged(c.detail, roles).map((r) => (
                      <span key={r.id} className="flex items-center gap-1.5 text-xs">
                        <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
                        <button
                          type="button"
                          disabled={!!deciding}
                          onClick={() => {
                            setDeciding(r.id)
                            void onEquipment(r.id, 'confirm').finally(() => setDeciding(null))
                          }}
                          className="rounded bg-pine px-1.5 py-0.5 font-semibold text-white disabled:opacity-50"
                          title="Yes, this is powered equipment: under-18s can't work it"
                        >
                          Is equipment
                        </button>
                        <button
                          type="button"
                          disabled={!!deciding}
                          onClick={() => {
                            setDeciding(r.id)
                            void onEquipment(r.id, 'reject').finally(() => setDeciding(null))
                          }}
                          className="rounded border border-rule px-1.5 py-0.5 font-semibold text-ink-2 hover:border-ink disabled:opacity-50"
                        >
                          Not equipment
                        </button>
                      </span>
                    ))}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
        {children}
      </div>
      <div className="shrink-0 border-t border-rule px-4 py-3">
        <SolveButton state={solve} onSolve={onSolve} />
        {readiness && !readiness.ready && (
          <p className="mt-2 text-xs text-muted">Some items aren't done yet. A build now uses whatever is set so far.</p>
        )}
      </div>
    </aside>
  )
}
