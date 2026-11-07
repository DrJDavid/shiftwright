// Picks the live API or the in-browser mock.
//   ?api=live | ?api=mock in the URL (remembered), else VITE_API_MODE, else "live".
// Demo key (sent as X-Demo-Key when the server sets DEMO_KEY): ?key=... (remembered), else VITE_DEMO_KEY.
import { createApi } from './client'
import { createMockFetch } from '../mock/server'

export type ApiMode = 'live' | 'mock'

function remembered(param: string, storageKey: string): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get(param)
  if (fromUrl !== null) {
    try {
      localStorage.setItem(storageKey, fromUrl)
    } catch {
      /* storage unavailable */
    }
    return fromUrl
  }
  try {
    return localStorage.getItem(storageKey)
  } catch {
    return null
  }
}

function pickMode(): ApiMode {
  const v = remembered('api', 'sw.apiMode')
  if (v === 'live' || v === 'mock') return v
  return import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'live'
}

function pickDemoKey(): string | null {
  const key = remembered('key', 'sw.demoKey') || (import.meta.env.VITE_DEMO_KEY as string | undefined) || null
  // Keep the key out of the address bar (the demo runs on a projector).
  const url = new URL(window.location.href)
  if (url.searchParams.has('key')) {
    url.searchParams.delete('key')
    window.history.replaceState(null, '', url)
  }
  return key
}

export const apiMode: ApiMode = pickMode()
const demoKey = pickDemoKey()
export const api = createApi(apiMode === 'mock' ? createMockFetch() : (input, init) => fetch(input, init), { demoKey })
