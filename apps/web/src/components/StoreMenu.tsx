import { useEffect, useRef, useState } from 'react'
import { LOCALITIES, missingTemplates } from '../lib/stores'

type Props = { onNew: (template: string) => Promise<void> }

/** Header menu: load a demo store for a locality, or start an empty store. Each choice creates a new store. */
export function StoreMenu({ onNew }: Props) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState(() => missingTemplates())
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  const pick = async (template: string, label: string) => {
    setBusy(template === 'empty' ? 'Creating store…' : `Loading ${label}…`)
    setError(null)
    try {
      await onNew(template)
      setOpen(false)
    } catch (e) {
      setError(`${label}: ${(e as Error).message}`)
      setMissing(missingTemplates())
    } finally {
      setBusy(null)
    }
  }

  const shown = LOCALITIES.filter((l) => !missing.has(l.template))

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
            <MenuItem key={l.id} title={l.label} detail="Big-box demo store with its local law pack" onClick={() => void pick(l.template, l.label)} disabled={!!busy} />
          ))}
          <div className="my-1 border-t border-rule-soft" />
          <MenuItem
            title="Start an empty store"
            detail="Default departments and roles; set up the rest in the chat."
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
