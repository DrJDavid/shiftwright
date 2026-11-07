import { ApiError } from '../api/client'

export const inputClass = (invalid?: boolean) =>
  `w-full rounded-md border bg-panel px-3 py-2 text-base outline-none focus:border-pine ${invalid ? 'border-gap' : 'border-rule'}`

export const primaryButton =
  'rounded-md bg-pine px-4 py-2.5 font-semibold text-white hover:bg-pine-dark disabled:cursor-not-allowed disabled:opacity-50'

/** Server error text a person can read (FastAPI validation errors arrive as JSON). */
export function readableError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const m = e.message.trim()
    if (m && !m.startsWith('[') && !m.startsWith('{')) return m
    return fallback
  }
  return e instanceof Error && e.message ? `${fallback} (${e.message})` : fallback
}
