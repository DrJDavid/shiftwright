import { createContext, useContext } from 'react'
import type { Api } from '../api/client'

/** What cards that talk to the API directly (csv_import) need. */
export type CardEnv = { api: Api; storeId: string; onConfigChanged: () => void }

export const CardEnvContext = createContext<CardEnv | null>(null)

export function useCardEnv(): CardEnv {
  const env = useContext(CardEnvContext)
  if (!env) throw new Error('CardEnvContext missing')
  return env
}
