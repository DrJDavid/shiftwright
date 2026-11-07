import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import { markMissing, type SampleTemplate } from '../lib/stores'
import { readableError } from './ui'

/** Copies a demo template into a sample workplace I own, then opens it. */
export function useOpenSample() {
  const api = useApi()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function open(t: SampleTemplate) {
    setBusy(t.template)
    setError(null)
    try {
      const cfg = await api.sampleWorkplace(t.template)
      navigate(`/w/${encodeURIComponent(cfg.store.id)}`)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 422)) {
        markMissing(t.template)
        setError(`${t.label} isn't on this server yet.`)
      } else {
        setError(readableError(e, `Couldn't open ${t.label}.`))
      }
    } finally {
      setBusy(null)
    }
  }

  return { open, busy, error }
}
