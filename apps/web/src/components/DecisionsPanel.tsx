import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../api/context'
import type { Decision } from '../api/client'
import { fmtMoney } from '../lib/format'

/** "N decisions waiting" on the schedule, and the panel that answers them. Reads the stored tradeoffs from
 *  the API (not a chat card), so it works after a refresh and doesn't depend on a live chat stream. */
export function DecisionsLink({ storeId, buildKey, onRebuild }: { storeId: string; buildKey: string; onRebuild: () => void }) {
  const api = useApi()
  const [items, setItems] = useState<Decision[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [changed, setChanged] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await api.decisions(storeId)).decisions)
    } catch {
      setItems([]) // older API or no build yet: nothing to show
    }
  }, [api, storeId])
  useEffect(() => {
    setChanged(false)
    void load()
  }, [load, buildKey])

  const waiting = items.filter((d) => !d.answered).length
  if (items.length === 0) return null

  const choose = async (d: Decision, optionId: string) => {
    setBusy(optionId)
    setError(null)
    try {
      const r = await api.decide(storeId, d.id, optionId)
      if (r.decision === 'approve' || r.decision === 'drop') setChanged(true)
      await load()
    } catch (e) {
      setError((e as Error).message)
      await load()
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="font-semibold text-pine-dark underline">
        {waiting > 0 ? `${waiting} ${waiting === 1 ? 'decision' : 'decisions'} waiting` : 'Decisions'}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-16" onClick={() => setOpen(false)}>
          <div className="w-full max-w-xl rounded-xl bg-paper p-5 text-sm text-ink shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Decisions">
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Decisions from this build</h2>
              <button type="button" onClick={() => setOpen(false)} className="text-muted hover:text-ink">
                Close
              </button>
            </div>
            <p className="mb-4 text-ink-2">
              The schedule kept your rules and budget. These are the places where changing one would cost or save real money. Numbers come from
              re-running the solver.
            </p>
            <ul className="space-y-3">
              {items.map((d) => {
                const picked = d.options.find((o) => o.id.endsWith(`:${d.answered}`))
                return (
                  <li key={d.id} className="rounded-lg border border-rule bg-panel p-3">
                    <p className="font-medium">{d.question}</p>
                    {picked ? (
                      <p className="mt-2 text-pine-dark">Decided: {picked.label}.</p>
                    ) : (
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        {d.options.map((o) => (
                          <button
                            key={o.id}
                            type="button"
                            disabled={!!busy}
                            onClick={() => void choose(d, o.id)}
                            className="rounded-md border border-rule bg-paper px-3 py-2 text-left hover:border-ink disabled:opacity-50"
                          >
                            <span className="block font-semibold">
                              {busy === o.id ? 'Saving…' : o.label}
                              {o.cost_dollars > 0 && <span className="font-normal text-ink-2"> · {fmtMoney(o.cost_dollars)}</span>}
                            </span>
                            <span className="block text-xs text-ink-2">{o.effect}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            {error && <p className="mt-3 text-gap">{error}</p>}
            {changed && (
              <div className="mt-4 flex items-center justify-between rounded-lg bg-pine-wash px-3 py-2">
                <span className="text-pine-dark">Your answers apply on the next build.</span>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false)
                    onRebuild()
                  }}
                  className="rounded-md bg-pine px-3 py-1.5 font-semibold text-white"
                >
                  Rebuild now
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
