import { useEffect, useRef, useState } from 'react'

type Props = { onNew: (kind: 'demo' | 'empty') => Promise<void> }

/** Header menu: start over with the demo store (Store #0417, 60 people) or an empty store. */
export function StoreMenu({ onNew }: Props) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  const pick = async (kind: 'demo' | 'empty') => {
    setBusy(kind === 'demo' ? 'Loading demo store…' : 'Creating store…')
    try {
      await onNew(kind)
      setOpen(false)
    } finally {
      setBusy(null)
    }
  }

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
        <div className="absolute top-full right-0 z-50 mt-1.5 w-72 rounded-lg border border-rule bg-panel p-1.5 text-ink shadow-xl">
          <MenuItem title="Load the demo store" detail="Store #0417, Austin TX: 60 people, 14 roles, trucks Tue/Thu/Sat." onClick={() => void pick('demo')} disabled={!!busy} />
          <MenuItem title="Start an empty store" detail="Default departments and roles; set up the rest in the chat." onClick={() => void pick('empty')} disabled={!!busy} />
          <p className="px-2.5 pt-1.5 pb-1 text-xs text-muted">Both create a new store. The current one stays on the server.</p>
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
