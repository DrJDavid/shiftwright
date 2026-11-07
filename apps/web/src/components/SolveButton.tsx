import { useEffect, useState } from 'react'

export type SolveState = { status: 'idle' } | { status: 'running'; startedAt: number } | { status: 'error'; message: string }

type Props = { state: SolveState; onSolve: () => void; compact?: boolean; label?: string; disabled?: boolean }

export function SolveButton({ state, onSolve, compact, label = 'Build schedule', disabled }: Props) {
  const running = state.status === 'running'
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [running])
  const elapsed = running ? Math.max(0, Math.floor((now - state.startedAt) / 1000)) : 0

  return (
    <div className={compact ? 'flex items-center gap-2' : 'space-y-2'}>
      <button
        type="button"
        onClick={onSolve}
        disabled={running || disabled}
        className={`relative overflow-hidden rounded-md bg-pine font-semibold text-white hover:bg-pine-dark disabled:cursor-not-allowed disabled:opacity-60 ${
          compact ? 'px-3 py-1 text-xs' : 'w-full px-4 py-2.5'
        }`}
      >
        {running ? `Building… ${elapsed}s` : label}
      </button>
      {running && !compact && (
        <div className="sw-progress relative h-1 overflow-hidden rounded-full bg-pine-wash" aria-hidden />
      )}
      {state.status === 'error' && <p className="text-sm text-gap">Build failed: {state.message}</p>}
    </div>
  )
}
