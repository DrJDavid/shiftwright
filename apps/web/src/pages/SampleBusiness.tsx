import { useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import type { GeneratedDifficulty, GeneratedRequest } from '../api/protocol'
import { US_STATES } from '../lib/stores'
import { inputClass, readableError } from './ui'

const KINDS: {
  sector: GeneratedRequest['sector']
  label: string
  blurb: string
}[] = [
  {
    sector: 'food',
    label: 'Restaurant',
    blurb: 'Kitchen and front of house, with its own exports.',
  },
  {
    sector: 'retail',
    label: 'Retail store',
    blurb: 'Departments, a stockroom and a forecast.',
  },
]

const DIFFICULTIES: { value: GeneratedDifficulty; label: string }[] = [
  { value: 'easy', label: 'Clean' },
  { value: 'tight', label: 'Tight budget' },
  { value: 'legal_trap', label: 'Legal traps' },
  { value: 'messy', label: 'Messy exports' },
]

/** PUNCHLIST B7: one click makes a generated business (A3) and opens it with the manager's message sent. */
export function SampleBusiness() {
  const api = useApi()
  const navigate = useNavigate()
  const ids = useId()
  const [more, setMore] = useState(false)
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [size, setSize] = useState<'S' | 'M'>('S')
  const [difficulty, setDifficulty] = useState<GeneratedDifficulty>('easy')
  const [seed, setSeed] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function start(sector: GeneratedRequest['sector']) {
    const req: GeneratedRequest = { sector, size, difficulty }
    if (state) req.state = state
    if (city.trim()) req.city = city.trim().toLowerCase()
    if (/^\d+$/.test(seed.trim())) req.seed = Number(seed.trim())
    setBusy(sector)
    setError(null)
    try {
      const g = await api.generatedWorkplace(req)
      navigate(`/w/${encodeURIComponent(g.store_id)}`, {
        state: { kickoff: g.kickoff },
      })
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? 'That’s a lot of sample businesses in a few minutes. Try again in a little while.'
          : readableError(err, 'Couldn’t make a sample business.'),
      )
      setBusy(null)
    }
  }

  return (
    <section aria-labelledby={`${ids}-h`} className="rounded-lg border border-rule bg-panel p-6">
      <h2 id={`${ids}-h`} className="text-lg font-semibold">
        Try it with a sample business
      </h2>
      <p className="mt-1 text-sm text-ink-2">A made-up company with a team, exports and a few surprises. Watch it set itself up.</p>
      <div className="mt-4 grid gap-3">
        {KINDS.map((k) => (
          <button
            key={k.sector}
            type="button"
            disabled={!!busy}
            onClick={() => void start(k.sector)}
            className="rounded-lg border-2 border-ink/20 px-4 py-4 text-left hover:border-pine disabled:opacity-50"
          >
            <span className="block text-base font-semibold">{k.label}</span>
            <span className="block text-sm text-muted">{busy === k.sector ? 'Making the company…' : k.blurb}</span>
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-gap-wash px-3 py-2 text-sm text-gap">
          {error}
        </p>
      )}
      <button
        type="button"
        aria-expanded={more}
        onClick={() => setMore((m) => !m)}
        className="mt-3 text-sm font-semibold text-pine-dark underline"
      >
        More options
      </button>
      {more && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <label className="block">
            <span className="mb-1 block text-ink-2">City</span>
            <input className={inputClass()} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Default for the kind" />
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-2">State</span>
            <select className={inputClass()} value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">Default</option>
              {US_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-2">Size</span>
            <select className={inputClass()} value={size} onChange={(e) => setSize(e.target.value as 'S' | 'M')}>
              <option value="S">Small</option>
              <option value="M">Medium</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-ink-2">Seed (optional)</span>
            <input
              className={inputClass()}
              inputMode="numeric"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="Random"
            />
          </label>
          <fieldset className="col-span-2">
            <legend className="mb-1 text-ink-2">Difficulty</legend>
            <div className="flex flex-wrap gap-2">
              {DIFFICULTIES.map((d) => (
                <label
                  key={d.value}
                  className={`cursor-pointer rounded-full border px-3 py-1 ${difficulty === d.value ? 'border-pine bg-pine-wash text-pine-dark' : 'border-rule'}`}
                >
                  <input
                    type="radio"
                    className="sr-only"
                    name={`${ids}-difficulty`}
                    checked={difficulty === d.value}
                    onChange={() => setDifficulty(d.value)}
                  />
                  {d.label}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      )}
    </section>
  )
}
