// Creating stores: empty template, or a demo store per locality (API v1.2 fixture templates).
import { api, apiMode } from '../api'
import { ApiError } from '../api/client'
import type { StoreConfig } from '../contracts'
import { demoFor } from './demoStore'

export const STORE_KEY = `sw.storeId.${apiMode}`

export type Locality = { id: string; label: string; template: string }

/**
 * WS4 builds these; WS6 exposes them as templates. Austin is `demo` (v1.2); the others are `demo_<id>`.
 * No law claims here: the rulebook shows each store's law pack with citations.
 */
export const LOCALITIES: Locality[] = [
  { id: 'austin', label: 'Austin, TX', template: 'demo' },
  { id: 'chicago', label: 'Chicago, IL', template: 'demo_chicago' },
  { id: 'seattle', label: 'Seattle, WA', template: 'demo_seattle' },
  { id: 'sf', label: 'San Francisco, CA', template: 'demo_sf' },
]

const MISSING_KEY = 'sw.missingTemplates'

/** Templates the server rejected this session (not built yet), so the menu can hide them. */
export function missingTemplates(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(MISSING_KEY) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

function markMissing(t: string) {
  const s = missingTemplates()
  s.add(t)
  try {
    sessionStorage.setItem(MISSING_KEY, JSON.stringify([...s]))
  } catch {
    /* storage unavailable */
  }
}

export class TemplateMissing extends Error {}

const EMPTY = {
  template: (import.meta.env.VITE_STORE_TEMPLATE as 'bigbox_small' | 'bigbox_mid' | 'empty' | undefined) ?? 'bigbox_mid',
  name: 'Store #0417',
  jurisdiction: { state: 'TX', city: 'austin' },
}

export type BlankStore = { name: string; state: string; city: string }

/**
 * `template` = "empty" (big-box roles, legacy default), "blank" (no roles: any business, set up in chat; needs
 * `blank`), or a demo template ("demo", "demo_chicago", …). Remembers the new store id.
 */
export async function createStore(template: string, blank?: BlankStore): Promise<StoreConfig> {
  let cfg: StoreConfig
  if (template === 'blank' && blank) {
    cfg = await api.createStore({
      template: 'empty',
      name: blank.name.trim() || 'My business',
      jurisdiction: { state: blank.state.trim().toUpperCase(), city: blank.city.trim() ? blank.city.trim().toLowerCase() : null },
    })
  } else if (template === 'empty') {
    cfg = await api.createStore(EMPTY)
  } else {
    try {
      cfg = await api.createStore({ template: template as `demo_${string}` })
    } catch (e) {
      const unknown = e instanceof ApiError && (e.status === 404 || e.status === 422)
      if (!unknown) throw e
      if (template !== 'demo') {
        markMissing(template)
        throw new TemplateMissing(`That demo store isn't on this server yet.`)
      }
      // API older than v1.2: load the bundled Austin fixture with a full-config PUT.
      cfg = await api.createStore(EMPTY)
      cfg = await api.putConfig(cfg.store.id, demoFor(cfg.store.id))
    }
  }
  try {
    localStorage.setItem(STORE_KEY, cfg.store.id)
  } catch {
    /* storage unavailable */
  }
  return cfg
}

/** `?demo` → Austin, `?demo=chicago` → that locality's template. */
export function templateFromDemoParam(v: string): string {
  return LOCALITIES.find((l) => l.id === v.toLowerCase())?.template ?? 'demo'
}
