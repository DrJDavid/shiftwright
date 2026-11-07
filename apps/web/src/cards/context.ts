import { createContext, useContext } from 'react'
import type { Api } from '../api/client'
import type { Sector } from '../contracts'

/** What cards that talk to the API directly (csv_import) need. */
export type CardEnv = { api: Api; storeId: string; onConfigChanged: () => void; sector?: Sector | null }

export const CardEnvContext = createContext<CardEnv | null>(null)

export function useOptionalCardEnv(): CardEnv | null {
  return useContext(CardEnvContext)
}

export function useCardEnv(): CardEnv {
  const env = useContext(CardEnvContext)
  if (!env) throw new Error('CardEnvContext missing')
  return env
}
