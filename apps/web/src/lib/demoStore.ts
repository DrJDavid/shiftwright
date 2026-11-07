// WS4's demo store (Store #0417, Austin), bundled so the leader can load it into the real API
// without touching JSON. Read-only import of packages/scenarios/fixtures/demo_store.json.
import type { StoreConfig } from '../contracts'

const files = import.meta.glob<StoreConfig>('../../../../packages/scenarios/fixtures/demo_store.json', {
  eager: true,
  import: 'default',
})

export const demoStoreConfig: StoreConfig | undefined = Object.values(files)[0]

/** The demo config re-keyed to an existing store id (PUT /config is a full replace). */
export function demoFor(storeId: string): StoreConfig {
  if (!demoStoreConfig) throw new Error('Demo store fixture not found (packages/scenarios/fixtures/demo_store.json).')
  const cfg = structuredClone(demoStoreConfig)
  cfg.store = { ...cfg.store, id: storeId }
  return cfg
}
