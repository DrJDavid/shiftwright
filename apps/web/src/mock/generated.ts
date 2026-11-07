// MOCK-ONLY stand-in for A3 `POST /workplaces/generated`: an empty store plus "cached" CSV previews whose
// commit copies the matching part of the tiny fixture. Shapes follow contracts/API.md; the data is the fixture's.
import type { StoreConfig } from '../contracts'
import type { CsvImportKind, GeneratedRequest, ImportPreview, Kickoff } from '../api/protocol'
import { mockStoreConfig } from './fixture'

export type CachedImport = { preview: ImportPreview; apply: (cfg: StoreConfig) => StoreConfig }

const SECTORS = ['retail', 'food']
const SIZES = ['S', 'M']
const DIFFICULTIES = ['easy', 'normal', 'tight', 'legal_trap', 'messy']

/** A3 rejects anything else with 400. */
export function badGeneratedRequest(r: Partial<GeneratedRequest>): string | null {
  if (!SECTORS.includes(String(r.sector))) return 'sector must be retail or food'
  if (r.size != null && !SIZES.includes(r.size)) return 'size must be S or M'
  if (r.difficulty != null && !DIFFICULTIES.includes(r.difficulty)) return `difficulty must be one of ${DIFFICULTIES.join(', ')}`
  if (r.seed != null && !(Number.isInteger(r.seed) && r.seed >= 0 && r.seed <= 999999)) return 'seed must be 0..999999'
  return null
}

function preview(kind: CsvImportKind, mapping: Record<string, string>, rows: Record<string, unknown>[]): ImportPreview {
  return {
    kind,
    columns: Object.keys(mapping),
    proposed_mapping: mapping,
    unmapped_required: [],
    rows_preview: rows.slice(0, 5),
    row_count: rows.length,
    warnings: [],
    target_fields: Object.values(mapping),
    required_fields: [],
    required_any_of: [],
  }
}

export function mockGenerated(id: string, req: GeneratedRequest) {
  const food = req.sector === 'food'
  const state = req.state ?? (food ? 'IL' : 'TX')
  const city = req.city ?? (food ? 'chicago' : 'austin')
  const name = food ? 'Mock Diner' : 'Mock Market'
  const source = mockStoreConfig(id, 'bigbox_small', name, state, city)
  const config = mockStoreConfig(id, 'empty', name, state, city)
  config.store = { ...config.store, sector: req.sector }

  const roster = source.employees.map((e) => ({ 'Emp ID': e.id, Name: e.name, Age: e.age, Dept: e.home_department_id, Rate: e.wage_per_hour }))
  const training = source.employees.flatMap((e) => e.trained_role_ids.map((r) => ({ 'Emp ID': e.id, Skill: r })))
  const forecast = source.demand.map((d) => ({ Role: d.role_id, Day: d.day, Start: d.start, End: d.end, 'Req HC': d.headcount }))
  const cache = new Map<CsvImportKind, CachedImport>([
    [
      'roster',
      {
        preview: preview('roster', { 'Emp ID': 'employee_id', Name: 'name', Age: 'age', Dept: 'home_department', Rate: 'wage_per_hour' }, roster),
        apply: (c) => ({ ...c, employees: source.employees.map((e) => ({ ...e, trained_role_ids: [] })) }),
      },
    ],
    [
      'training',
      {
        preview: preview('training', { 'Emp ID': 'employee_id', Skill: 'role' }, training),
        apply: (c) => ({
          ...c,
          employees: c.employees.map((e) => ({ ...e, trained_role_ids: source.employees.find((s) => s.id === e.id)?.trained_role_ids ?? [] })),
        }),
      },
    ],
    [
      'forecast',
      {
        preview: preview('forecast', { Role: 'role', Day: 'day', Start: 'start', End: 'end', 'Req HC': 'headcount' }, forecast),
        apply: (c) => ({ ...c, demand: source.demand }),
      },
    ],
  ])
  const kickoff: Kickoff = {
    message: `Hi, I manage ${name}. Here's my team and what we need each week. My exports are attached.`,
    attachments: [...cache].map(([kind, x]) => ({ kind, filename: `${kind}.csv`, row_count: x.preview.row_count })),
  }
  return { config, cache, kickoff, seed: req.seed ?? 417 }
}
