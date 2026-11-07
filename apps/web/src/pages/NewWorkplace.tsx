import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../api/context'
import type { Sector } from '../contracts'
import { SECTOR_CHOICES, US_STATES, useSampleTemplates } from '../lib/stores'
import { AccountLinks } from './AccountLinks'
import { Field, PageShell } from './Shell'
import { inputClass, primaryButton, readableError } from './ui'
import { useOpenSample } from './useOpenSample'
import { SampleBusiness } from './SampleBusiness'

type Errors = {
  name?: string
  sector?: string
  city?: string
  state?: string
  form?: string
}

export function NewWorkplace() {
  const api = useApi()
  const navigate = useNavigate()
  const samples = useSampleTemplates(api)
  const sample = useOpenSample()
  const [name, setName] = useState('')
  const [sector, setSector] = useState<Sector | null>(null)
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [busy, setBusy] = useState(false)
  const [showSamples, setShowSamples] = useState(false)

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    const e: Errors = {}
    if (!name.trim()) e.name = 'Give your workplace a name.'
    if (!sector) e.sector = 'Pick the closest match.'
    if (!city.trim()) e.city = 'Enter the city.'
    if (!state) e.state = 'Pick the state.'
    setErrors(e)
    if (Object.keys(e).length || !sector) return
    setBusy(true)
    try {
      const cfg = await api.createStore({
        template: 'empty',
        name: name.trim(),
        sector,
        ...(description.trim() ? { business_description: description.trim() } : {}),
        jurisdiction: { state, city: city.trim().toLowerCase() },
      })
      navigate(`/w/${encodeURIComponent(cfg.store.id)}`)
    } catch (err) {
      setErrors({ form: readableError(err, 'Couldn’t create the workplace.') })
      setBusy(false)
    }
  }

  return (
    <PageShell right={<AccountLinks />} wide>
      <h1 className="text-2xl font-semibold tracking-tight">New workplace</h1>
      <p className="mt-1 text-ink-2">Three questions. The chat sets up the rest with you.</p>
      <div className="mt-6 grid items-start gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div>
          <form noValidate onSubmit={(e) => void submit(e)} className="space-y-5 rounded-lg border border-rule bg-panel p-6">
            <Field label="Name" error={errors.name}>
              {(a) => (
                <input
                  {...a}
                  className={inputClass(!!errors.name)}
                  placeholder="Harbor Grill"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              )}
            </Field>

            <fieldset>
              <legend className="text-sm font-semibold text-ink">What kind of business?</legend>
              <div className="mt-1 grid grid-cols-2 gap-2">
                {SECTOR_CHOICES.map((c) => (
                  <label
                    key={c.sector}
                    className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium ${
                      sector === c.sector ? 'border-pine bg-pine-wash text-pine-dark' : 'border-rule hover:border-ink-2'
                    }`}
                  >
                    <input
                      type="radio"
                      name="sector"
                      value={c.sector}
                      checked={sector === c.sector}
                      onChange={() => setSector(c.sector)}
                      className="accent-pine"
                    />
                    {c.label}
                  </label>
                ))}
              </div>
              {errors.sector && (
                <span role="alert" className="mt-1 block text-sm text-gap">
                  {errors.sector}
                </span>
              )}
            </fieldset>

            <div className="grid grid-cols-[1fr_6rem] gap-3">
              <Field label="City" error={errors.city}>
                {(a) => (
                  <input
                    {...a}
                    className={inputClass(!!errors.city)}
                    placeholder="Chicago"
                    autoComplete="address-level2"
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                  />
                )}
              </Field>
              <Field label="State" error={errors.state}>
                {(a) => (
                  <select {...a} className={inputClass(!!errors.state)} value={state} onChange={(e) => setState(e.target.value)}>
                    <option value="">–</option>
                    {US_STATES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>

            <Field label="In a few words (optional)" hint="e.g. “family taqueria, open late on weekends”">
              {(a) => (
                <input
                  {...a}
                  className={inputClass()}
                  maxLength={200}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              )}
            </Field>

            {errors.form && (
              <p role="alert" className="rounded-md bg-gap-wash px-3 py-2 text-sm text-gap">
                {errors.form}
              </p>
            )}
            <button type="submit" disabled={busy} className={`w-full ${primaryButton}`}>
              {busy ? 'Creating…' : 'Create workplace'}
            </button>
          </form>

          <div className="mt-6 text-sm">
            <button
              type="button"
              aria-expanded={showSamples}
              onClick={() => setShowSamples((s) => !s)}
              className="font-semibold text-pine-dark underline"
            >
              Or explore a sample workplace
            </button>
            {showSamples && (
              <div className="mt-2 rounded-lg border border-rule bg-panel p-2">
                {samples.map((t) => (
                  <button
                    key={t.template}
                    type="button"
                    disabled={!!sample.busy}
                    onClick={() => void sample.open(t)}
                    className="block w-full rounded-md px-3 py-2 text-left hover:bg-paper disabled:opacity-50"
                  >
                    <span className="font-semibold">{t.label}</span>
                    <span className="block text-xs text-muted">
                      {sample.busy === t.template ? 'Opening…' : 'A copy with a team and a week of demand, yours to change.'}
                    </span>
                  </button>
                ))}
                {sample.error && <p className="px-3 py-1 text-xs text-gap">{sample.error}</p>}
              </div>
            )}
          </div>
        </div>
        <SampleBusiness />
      </div>
    </PageShell>
  )
}
