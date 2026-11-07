import { useEffect, useRef, useState } from 'react'
import { api, apiMode } from '../api'
import { LOCALITIES, missingTemplates, type BlankStore } from '../lib/stores'

type Props = { onNew: (template: string, blank?: BlankStore) => Promise<void> }

/** Header menu: load a demo store for a locality, or start an empty store. Each choice creates a new store. */
export function StoreMenu({ onNew }: Props) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [blank, setBlank] = useState<BlankStore>({ name: '', state: '', city: '' })
  const [missing, setMissing] = useState(() => missingTemplates())
  // v1.4: the server lists its templates; older servers / the mock fall back to the built-in list.
  const [served, setServed] = useState<{ template: string; label: string }[] | null>(null)
  useEffect(() => {
    api
      .templates()
      .then((r) =>
        setServed(
          r.templates
            .filter((t) => t.id === 'demo' || t.id.startsWith('demo_'))
            .map((t) => ({ template: t.id, label: t.label.replace(/\s*\(\d+ staff\)$/, '') + (t.label.match(/\((\d+ staff)\)$/) ? ` · ${t.label.match(/\((\d+ staff)\)$/)![1]}` : '') })),
        ),
      )
      .catch(() => setServed(null))
  }, [])
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  const pick = async (template: string, label: string) => {
    setBusy(template === 'empty' || template === 'blank' ? 'Creating store…' : `Loading ${label}…`)
    setError(null)
    try {
      await onNew(template, template === 'blank' ? blank : undefined)
      setOpen(false)
    } catch (e) {
      setError(`${label}: ${(e as Error).message}`)
      setMissing(missingTemplates())
    } finally {
      setBusy(null)
    }
  }

  const shown = served ?? LOCALITIES.filter((l) => !missing.has(l.template) && (apiMode === 'live' || l.template === 'demo'))

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="rounded border border-white/30 px-2.5 py-1 text-sm font-medium text-white/90 hover:border-white hover:text-white"
      >
        {busy ?? 'Store ▾'}
      </button>
      {open && (
        <div className="absolute top-full right-0 z-50 mt-1.5 w-80 rounded-lg border border-rule bg-panel p-1.5 text-ink shadow-xl">
          <div className="px-2.5 pt-1 pb-0.5 text-xs font-semibold tracking-wide text-muted uppercase">Load a demo store</div>
          {shown.map((l) => (
            <MenuItem key={l.template} title={l.label} detail="Demo store with its local law pack" onClick={() => void pick(l.template, l.label)} disabled={!!busy} />
          ))}
          <div className="my-1 border-t border-rule-soft" />
          <form
            className="rounded-md px-2.5 py-2 hover:bg-paper"
            onSubmit={(e) => {
              e.preventDefault()
              if (/^[A-Za-z]{2}$/.test(blank.state)) void pick('blank', 'New business')
            }}
          >
            <span className="block text-sm font-semibold">Start from scratch</span>
            <span className="block text-xs text-muted">Any kind of business. The chat asks what it is and sets up roles and staffing.</span>
            <div className="mt-1.5 grid grid-cols-[1fr_3rem_6rem] gap-1">
              <input
                aria-label="Business name"
                placeholder="Business name"
                className="min-w-0 rounded border border-rule px-1.5 py-1 text-sm"
                value={blank.name}
                onChange={(e) => setBlank({ ...blank, name: e.target.value })}
              />
              <input
                aria-label="State"
                placeholder="ST"
                maxLength={2}
                className="rounded border border-rule px-1.5 py-1 text-sm uppercase"
                value={blank.state}
                onChange={(e) => setBlank({ ...blank, state: e.target.value })}
              />
              <input
                aria-label="City"
                placeholder="City"
                className="min-w-0 rounded border border-rule px-1.5 py-1 text-sm"
                value={blank.city}
                onChange={(e) => setBlank({ ...blank, city: e.target.value })}
              />
            </div>
            <button
              type="submit"
              disabled={!!busy || !/^[A-Za-z]{2}$/.test(blank.state)}
              className="mt-1.5 rounded bg-ink px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40"
            >
              Start
            </button>
          </form>
          <MenuItem
            title="Start a big-box store"
            detail="Default retail departments and roles; set up the rest in the chat."
            onClick={() => void pick('empty', 'Empty store')}
            disabled={!!busy}
          />
          {error && <p className="px-2.5 py-1 text-xs text-gap">{error}</p>}
          <p className="px-2.5 pt-1.5 pb-1 text-xs text-muted">Each choice creates a new store. The current one stays on the server.</p>
        </div>
      )}
    </div>
  )
}

function MenuItem({ title, detail, onClick, disabled }: { title: string; detail: string; onClick: () => void; disabled: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="block w-full rounded-md px-2.5 py-2 text-left hover:bg-paper disabled:opacity-50">
      <span className="block text-sm font-semibold">{title}</span>
      <span className="block text-xs text-muted">{detail}</span>
    </button>
  )
}
