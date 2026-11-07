import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import { useAuth } from '../auth/context'
import { Field, PageShell } from './Shell'
import { inputClass, primaryButton, readableError } from './ui'

type Mode = 'signup' | 'login'
type Errors = { name?: string; email?: string; password?: string; form?: string }

const MIN_PASSWORD = 8

function validate(mode: Mode, name: string, email: string, password: string): Errors {
  const e: Errors = {}
  if (mode === 'signup' && !name.trim()) e.name = 'Enter your name.'
  if (!email.trim()) e.email = 'Enter your email.'
  else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) e.email = 'That doesn’t look like an email address.'
  if (!password) e.password = 'Enter a password.'
  else if (mode === 'signup' && password.length < MIN_PASSWORD) e.password = `Use at least ${MIN_PASSWORD} characters.`
  return e
}

export function AuthPage({ mode }: { mode: Mode }) {
  const api = useApi()
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [busy, setBusy] = useState(false)
  // Set with signedIn() so this page's own redirect wins over "already signed in → /workplaces".
  const [done, setDone] = useState(false)
  const signup = mode === 'signup'

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    const found = validate(mode, name, email, password)
    setErrors(found)
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      const { user } = signup
        ? await api.signup({ name: name.trim(), email: email.trim(), password })
        : await api.login({ email: email.trim(), password })
      setDone(true)
      auth.signedIn(user)
      navigate(signup ? '/workplaces/new' : (from ?? '/workplaces'), { replace: true })
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setErrors({ email: 'An account with that email already exists.' })
      else if (e instanceof ApiError && e.status === 401) setErrors({ form: 'Wrong email or password.' })
      else setErrors({ form: readableError(e, signup ? 'Couldn’t create your account.' : 'Couldn’t sign you in.') })
      setBusy(false)
    }
  }

  if (auth.state.status === 'in' && !done) return <Navigate to="/workplaces" replace />

  return (
    <PageShell
      right={
        signup ? (
          <Link to="/login" className="text-sm text-white/80 hover:text-white">
            Sign in
          </Link>
        ) : (
          <Link to="/signup" className="text-sm text-white/80 hover:text-white">
            Create an account
          </Link>
        )
      }
    >
      <h1 className="text-2xl font-semibold tracking-tight">{signup ? 'Create your account' : 'Sign in'}</h1>
      <p className="mt-1 text-ink-2">{signup ? 'Then set up your first workplace. It takes a few minutes.' : 'Welcome back.'}</p>
      <form noValidate onSubmit={(e) => void submit(e)} className="mt-6 space-y-4 rounded-lg border border-rule bg-panel p-6">
        {signup && (
          <Field label="Your name" error={errors.name}>
            {(a) => (
              <input
                {...a}
                className={inputClass(!!errors.name)}
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="Email" error={errors.email}>
          {(a) => (
            <input
              {...a}
              type="email"
              className={inputClass(!!errors.email)}
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
        {errors.email && signup && errors.email.includes('already exists') && (
          <p className="-mt-2 text-sm">
            <Link to="/login" className="font-semibold text-pine-dark underline">
              Sign in instead
            </Link>
          </p>
        )}
        <Field label="Password" error={errors.password} hint={signup ? `At least ${MIN_PASSWORD} characters.` : undefined}>
          {(a) => (
            <input
              {...a}
              type="password"
              className={inputClass(!!errors.password)}
              autoComplete={signup ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        {errors.form && (
          <p role="alert" className="rounded-md bg-gap-wash px-3 py-2 text-sm text-gap">
            {errors.form}
          </p>
        )}
        <button type="submit" disabled={busy} className={`w-full ${primaryButton}`}>
          {busy ? (signup ? 'Creating your account…' : 'Signing in…') : signup ? 'Create account' : 'Sign in'}
        </button>
      </form>
      <p className="mt-4 text-sm text-ink-2">
        {signup ? (
          <>
            Already have an account?{' '}
            <Link to="/login" className="font-semibold text-pine-dark underline">
              Sign in
            </Link>
          </>
        ) : (
          <>
            New to Shiftwright?{' '}
            <Link to="/signup" className="font-semibold text-pine-dark underline">
              Create an account
            </Link>
          </>
        )}
      </p>
    </PageShell>
  )
}
