import { createContext, useContext } from 'react'
import type { Api } from '../api/client'
import type { Sector } from '../contracts'
import type { RuleNames } from '../lib/ruleNames'

/** What cards that talk to the API directly (csv_import) need; `ruleNames` names rules in conflict_menu. */
export type CardEnv = { api: Api; storeId: string; onConfigChanged: () => void; sector?: Sector | null; ruleNames?: RuleNames }

export const CardEnvContext = createContext<CardEnv | null>(null)

export function useOptionalCardEnv(): CardEnv | null {
  return useContext(CardEnvContext)
}

export function useCardEnv(): CardEnv {
  const env = useContext(CardEnvContext)
  if (!env) throw new Error('CardEnvContext missing')
  return env
}
