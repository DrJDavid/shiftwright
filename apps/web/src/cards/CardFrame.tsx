import type { ReactNode } from 'react'

export type CardStatus = 'open' | 'submitting' | 'submitted' | 'cancelled'

/** Props every card component receives. `props` is the card's API.md props, unvalidated. */
export type CardProps<P, R> = {
  props: P
  status: CardStatus
  result?: R
  onSubmit: (result: R) => void
  onCancel: () => void
}

type FrameProps = {
  title: string
  status: CardStatus
  summary?: ReactNode
  children: ReactNode
  onCancel: () => void
  submitLabel: string
  canSubmit?: boolean
  formId: string
}

/** Shared chrome: open cards are forms; submitted cards lock to a one-line summary. */
export function CardFrame({ title, status, summary, children, onCancel, submitLabel, canSubmit = true, formId }: FrameProps) {
  if (status === 'submitted' || status === 'cancelled') {
    return (
      <div className="rounded-lg border border-rule bg-panel px-3.5 py-2.5 text-sm">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-semibold">{title}</span>
          <span className={status === 'submitted' ? 'text-pine' : 'text-muted'}>
            {status === 'submitted' ? 'Confirmed' : 'Skipped'}
          </span>
        </div>
        {status === 'submitted' && summary && <div className="mt-0.5 text-ink-2">{summary}</div>}
      </div>
    )
  }
  const busy = status === 'submitting'
  return (
    <div className="rounded-lg border-2 border-ink/80 bg-panel">
      <div className="border-b border-rule px-3.5 py-2.5 font-semibold">{title}</div>
      <fieldset disabled={busy} className="min-w-0 px-3.5 py-3">
        {children}
      </fieldset>
      <div className="flex justify-end gap-2 border-t border-rule px-3.5 py-2.5">
        <button type="button" onClick={onCancel} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-ink-2 hover:bg-paper">
          Skip for now
        </button>
        <button
          type="submit"
          form={formId}
          disabled={busy || !canSubmit}
          className="rounded-md bg-pine px-3.5 py-1.5 text-sm font-semibold text-white hover:bg-pine-dark disabled:opacity-50"
        >
          {busy ? 'Saving…' : submitLabel}
        </button>
      </div>
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
    </label>
  )
}

export const inputCls =
  'w-full rounded-md border border-rule bg-panel px-2.5 py-1.5 text-ink focus:border-pine focus:outline-none focus:ring-2 focus:ring-pine/20'
