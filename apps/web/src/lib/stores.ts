// Workplaces: the sample templates a user can explore, and the fields of a new workplace.
import { useEffect, useState } from 'react'
import { apiMode } from '../api'
import type { Api } from '../api/client'
import type { WorkplaceSummary } from '../api/protocol'
import type { Sector } from '../contracts'

/** Last workplace opened in this mode; the phone-sized employee view falls back to it. */
export const STORE_KEY = `sw.storeId.${apiMode}`

export function rememberStore(id: string) {
  try {
    localStorage.setItem(STORE_KEY, id)
  } catch {
    /* storage unavailable */
  }
}

export type SampleTemplate = { template: string; label: string }

/**
 * Built-in list for servers without `GET /api/templates` (and the mock, which only has Austin).
 * No law claims here: the rulebook shows each store's law pack with citations.
 */
const LOCALITIES: SampleTemplate[] = [
  { template: 'demo', label: 'Austin, TX' },
  { template: 'demo_chicago', label: 'Chicago, IL' },
  { template: 'demo_seattle', label: 'Seattle, WA' },
  { template: 'demo_sf', label: 'San Francisco, CA' },
  { template: 'demo_restaurant', label: 'Harbor Grill #12, Chicago IL' },
]

const MISSING_KEY = 'sw.missingTemplates'

/** Templates the server rejected this session (not built yet), so the menus can hide them. */
function missingTemplates(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(MISSING_KEY) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

export function markMissing(t: string) {
  const s = missingTemplates()
  s.add(t)
  try {
    sessionStorage.setItem(MISSING_KEY, JSON.stringify([...s]))
  } catch {
    /* storage unavailable */
  }
}

function sampleLabel(label: string): string {
  const staff = label.match(/\((\d+ staff)\)$/)
  return label.replace(/\s*\(\d+ staff\)$/, '') + (staff ? ` · ${staff[1]}` : '')
}

/** Demo templates this server can copy into a sample workplace (v1.4 `GET /api/templates`). */
export function useSampleTemplates(api: Api): SampleTemplate[] {
  const [served, setServed] = useState<SampleTemplate[] | null>(null)
  useEffect(() => {
    let live = true
    api
      .templates()
      .then(
        (r) =>
          live &&
          setServed(
            r.templates
              .filter((t) => t.id === 'demo' || t.id.startsWith('demo_'))
              .map((t) => ({ template: t.id, label: sampleLabel(t.label) })),
          ),
      )
      .catch(() => live && setServed(null))
    return () => {
      live = false
    }
  }, [api])
  if (served) return served
  const missing = missingTemplates()
  return LOCALITIES.filter((l) => !missing.has(l.template) && (apiMode === 'live' || l.template === 'demo'))
}

/** Sample copies (A1 `sample_of`) are listed under "Explore a sample", not with your own. */
export const isSample = (w: WorkplaceSummary) => w.sample_of != null

/** "What kind of business?" → `Store.sector`. */
export const SECTOR_CHOICES: { sector: Sector; label: string }[] = [
  { sector: 'food', label: 'Restaurant / café' },
  { sector: 'retail', label: 'Retail store' },
  { sector: 'hospitality', label: 'Hotel' },
  { sector: 'other', label: 'Other' },
]

export const sectorLabel = (s: Sector | null | undefined) => SECTOR_CHOICES.find((c) => c.sector === s)?.label ?? null

export { placeLabel } from './format'

export const US_STATES = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA',
  'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR',
  'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
]
