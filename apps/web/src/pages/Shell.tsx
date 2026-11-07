import { useId, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** Top bar + centered page body for everything outside the workspace. */
export function PageShell({ right, children, wide }: { right?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <div className="min-h-full bg-paper">
      <header className="flex items-center gap-4 border-b border-ink bg-ink px-6 py-3 text-white">
        <Link to="/" className="font-bold tracking-tight">
          Shiftwright
        </Link>
        <span className="ml-auto" />
        {right}
      </header>
      <main className={`mx-auto px-6 py-10 ${wide ? 'max-w-4xl' : 'max-w-md'}`}>{children}</main>
    </div>
  )
}

/** Label + control + inline error (or hint). `children` gets the control's id and its aria-describedby. */
export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string | null
  hint?: string
  children: (a: { id: string; 'aria-describedby'?: string; 'aria-invalid': boolean }) => ReactNode
}) {
  const id = useId()
  const note = error || hint
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-ink">
        {label}
      </label>
      <div className="mt-1">{children({ id, 'aria-describedby': note ? `${id}-note` : undefined, 'aria-invalid': !!error })}</div>
      {error ? (
        <p id={`${id}-note`} role="alert" className="mt-1 text-sm text-gap">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-note`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
