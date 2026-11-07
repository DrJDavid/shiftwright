import { useEffect, useState } from 'react'

// The demo store (60 people, 7 days) takes ~20–30 s. The bar is an estimate from elapsed time only.
const TYPICAL_S = 25

/** Overlay shown while a solve runs: elapsed seconds and an estimated bar. */
export function SolveProgress({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [])
  const s = Math.max(0, (now - startedAt) / 1000)
  const frac = Math.min(0.95, s / TYPICAL_S)
  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-panel/70 pt-24 backdrop-blur-[1px]" role="status" aria-live="polite">
      <div className="w-[26rem] rounded-lg border border-rule bg-panel p-5 shadow-lg">
        <div className="flex items-baseline justify-between">
          <h3 className="font-semibold">Building the week</h3>
          <span className="text-sm text-muted tabular-nums">{Math.floor(s)}s</span>
        </div>
        <p className="mt-1 text-sm text-ink-2">
          {s < 4
            ? 'Generating every legal shift for every person…'
            : s < TYPICAL_S
              ? 'Choosing shifts that cover demand within the budget and every rule…'
              : 'Still improving. It stops at its time limit and returns the best schedule found.'}
        </p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-pine-wash">
          <div className="h-full bg-pine transition-[width] duration-300" style={{ width: `${frac * 100}%` }} />
        </div>
        <p className="mt-2 text-xs text-muted">Usually 20–30 seconds for a store this size. A separate compliance check reviews it before you see it.</p>
      </div>
    </div>
  )
}
