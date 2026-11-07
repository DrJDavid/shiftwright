import { useEffect, useState } from 'react'
import { progressMessage } from '../lib/buildProgress'

/** The calm one-liner while a build runs: elapsed seconds, then "still improving", plus coverage if the server reports it. */
export function BuildProgressLine({ startedAt, coveragePct }: { startedAt: number; coveragePct?: number | null }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [])
  return (
    <p className="text-sm text-ink-2" role="status" aria-live="polite">
      {progressMessage((now - startedAt) / 1000)}
      {coveragePct != null && <span className="block text-xs text-muted">Coverage so far: {Math.round(coveragePct)}%</span>}
    </p>
  )
}
