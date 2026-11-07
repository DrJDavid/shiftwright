// MOCK-ONLY: seeds the in-browser mock API from WS4's real StoreConfig fixtures in
// packages/scenarios/fixtures/, so mock data matches the contracts exactly.
// Template mapping: bigbox_mid -> demo_store.json (once WS4 ships it), otherwise tiny_store.json.
import type { StoreConfig } from '../contracts'

const fixtures = import.meta.glob<StoreConfig>('../../../../packages/scenarios/fixtures/*.json', {
  eager: true,
  import: 'default',
})

function fixture(name: string): StoreConfig | undefined {
  const hit = Object.entries(fixtures).find(([path]) => path.endsWith(`/${name}.json`))
  return hit?.[1]
}

export type Template = 'bigbox_small' | 'bigbox_mid' | 'empty'

export function mockStoreConfig(
  id: string,
  template: Template,
  name: string,
  state: string,
  city: string | null,
): StoreConfig {
  const base = (template === 'bigbox_mid' && fixture('demo_store')) || fixture('tiny_store')
  if (!base) throw new Error('No scenario fixtures found in packages/scenarios/fixtures/')
  const cfg: StoreConfig = structuredClone(base)
  cfg.config_version = 1
  cfg.store = { ...cfg.store, id, name, jurisdiction: { state, city } }
  if (template === 'empty') {
    cfg.employees = []
    cfg.demand = []
    cfg.events = []
  }
  return cfg
}
