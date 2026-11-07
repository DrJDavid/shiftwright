import { useEffect, useRef, useState } from 'react'
import { ApiError, type Api } from '../api/client'

export const PROGRESS_POLL_MS = 2000

/**
 * C4 (optional endpoint): while a build runs, poll GET /solve/progress every 2 s for coverage so far. Feature-detected
 * once: a 404 means this server doesn't have it, and it isn't asked again.
 */
export function useSolveProgress(api: Api, storeId: string | undefined, running: boolean, pollMs = PROGRESS_POLL_MS) {
  const supported = useRef<boolean | null>(null)
  const [coveragePct, setCoveragePct] = useState<number | null>(null)

  useEffect(() => {
    setCoveragePct(null)
    if (!running || !storeId || supported.current === false) return
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const p = await api.solveProgress(storeId)
        supported.current = true
        if (live && typeof p.coverage_pct === 'number') setCoveragePct(p.coverage_pct)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          supported.current = false
          return
        }
      }
      if (live) timer = setTimeout(() => void poll(), pollMs)
    }
    void poll()
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [api, storeId, running, pollMs])

  return coveragePct
}
