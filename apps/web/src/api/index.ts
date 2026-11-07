// Picks the live API or the in-browser mock.
//   ?api=live | ?api=mock in the URL (remembered), else VITE_API_MODE, else "mock".
// Flip the default to "live" once WS6 (apps/api) is merged.
import { createApi } from './client'
import { createMockFetch } from '../mock/server'

export type ApiMode = 'live' | 'mock'

function pickMode(): ApiMode {
  const fromUrl = new URLSearchParams(window.location.search).get('api')
  if (fromUrl === 'live' || fromUrl === 'mock') {
    try {
      localStorage.setItem('sw.apiMode', fromUrl)
    } catch {
      /* storage unavailable */
    }
    return fromUrl
  }
  try {
    const saved = localStorage.getItem('sw.apiMode')
    if (saved === 'live' || saved === 'mock') return saved
  } catch {
    /* storage unavailable */
  }
  return import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock'
}

export const apiMode: ApiMode = pickMode()
export const api = createApi(apiMode === 'mock' ? createMockFetch() : (input, init) => fetch(input, init))
