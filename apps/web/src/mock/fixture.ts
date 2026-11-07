// MOCK-ONLY store used until WS6 (apps/api) and WS4's demo_store.json land.
// Shaped exactly like contracts StoreConfig. Not real data; the UI shows a "Mock API" pill.
import type { DemandRequirement, Employee, Role, StoreConfig } from '../contracts'

const OPEN = 8 * 60
const CLOSE = 22 * 60

const roles: Role[] = [
  { id: 'lod', department_id: 'fos', name: 'Leader on duty', gap_penalty_per_hour: 120 },
  { id: 'cashier', department_id: 'fos', name: 'Cashier', gap_penalty_per_hour: 40 },
  { id: 'service_desk', department_id: 'fos', name: 'Service desk', gap_penalty_per_hour: 30 },
  { id: 'gm_stock', department_id: 'gm', name: 'GM stocking', gap_penalty_per_hour: 15 },
  { id: 'grocery', department_id: 'groc', name: 'Grocery', gap_penalty_per_hour: 20 },
  { id: 'fulfillment', department_id: 'ful', name: 'Order pickup', gap_penalty_per_hour: 25 },
]

type Seed = [id: string, name: string, dept: string, roles: string[], status: Employee['status'], wage: number, max: number, age?: number]
const seeds: Seed[] = [
  ['e01', 'Avery Lindqvist', 'fos', ['lod', 'service_desk', 'cashier'], 'full_time', 22.5, 40],
  ['e02', 'Marcus Oyelaran', 'fos', ['lod', 'cashier'], 'full_time', 21.75, 40],
  ['e03', 'Priya Natarajan', 'fos', ['lod', 'service_desk'], 'full_time', 23.0, 40],
  ['e04', 'Jordan Pike', 'fos', ['cashier', 'service_desk'], 'part_time', 15.25, 29],
  ['e05', 'Casey Moreno', 'fos', ['cashier'], 'part_time', 15.0, 29],
  ['e06', 'Dana Whitfield', 'fos', ['cashier', 'fulfillment'], 'part_time', 15.5, 29],
  ['e07', 'Sam Okafor', 'fos', ['cashier'], 'part_time', 15.0, 24, 17],
  ['e08', 'Riley Tran', 'fos', ['cashier', 'service_desk'], 'full_time', 16.75, 40],
  ['e09', 'Noor Haddad', 'gm', ['gm_stock', 'cashier'], 'full_time', 17.0, 40],
  ['e10', 'Theo Brandt', 'gm', ['gm_stock'], 'part_time', 15.75, 29],
  ['e11', 'Lena Kowalski', 'gm', ['gm_stock', 'grocery'], 'full_time', 17.25, 40],
  ['e12', 'Mateo Ruiz', 'groc', ['grocery'], 'full_time', 16.5, 40],
  ['e13', 'Hana Sato', 'groc', ['grocery', 'cashier'], 'part_time', 15.25, 29],
  ['e14', 'Ezra Collins', 'ful', ['fulfillment'], 'full_time', 16.75, 40],
  ['e15', 'Imani Brooks', 'ful', ['fulfillment', 'cashier'], 'part_time', 15.5, 29],
  ['e16', 'Wes Albright', 'gm', ['gm_stock', 'fulfillment'], 'part_time', 15.5, 29],
]

const employees: Employee[] = seeds.map(([id, name, dept, trained, status, wage, max, age]) => ({
  id,
  name,
  phone: `+1555010${id.slice(1)}`,
  age: age ?? 24,
  home_department_id: dept,
  trained_role_ids: trained,
  status,
  wage_per_hour: wage,
  min_hours_week: status === 'part_time' ? 12 : 32,
  max_hours_week: max,
  availability: [],
  hire_date: '2024-03-01',
}))

function demandFor(): DemandRequirement[] {
  const out: DemandRequirement[] = []
  let n = 0
  const add = (role_id: string, day: number, start: number, end: number, headcount: number) =>
    out.push({ id: `d${++n}`, role_id, day, start, end, headcount, source: 'corporate' })
  for (let day = 0; day < 7; day++) {
    const weekend = day >= 5
    add('lod', day, OPEN, CLOSE, 1)
    add('cashier', day, OPEN, CLOSE, 1)
    add('cashier', day, 11 * 60, 19 * 60, weekend ? 2 : 1)
    add('service_desk', day, 9 * 60, 21 * 60, 1)
    add('gm_stock', day, OPEN - 60, 15 * 60, day === 2 ? 3 : 1) // Wednesday truck
    add('grocery', day, OPEN - 60, 16 * 60, 1)
    add('fulfillment', day, 10 * 60, 20 * 60, weekend ? 2 : 1)
  }
  return out
}

export function mockStoreConfig(id: string, name: string, state: string, city: string | null): StoreConfig {
  return {
    contract_version: '1.0.0',
    config_version: 1,
    store: {
      id,
      name,
      jurisdiction: { state, city },
      timezone: 'America/Chicago',
      slot_minutes: 30,
      week_start: '2026-11-09',
      hours: Array.from({ length: 7 }, (_, day) => ({ day, open: OPEN, close: CLOSE })),
      pre_open_minutes: 60,
      post_close_minutes: 60,
    },
    departments: [
      { id: 'fos', name: 'Front of Store' },
      { id: 'gm', name: 'General Merchandise' },
      { id: 'groc', name: 'Grocery' },
      { id: 'ful', name: 'Fulfillment' },
    ],
    roles,
    role_tags: {},
    employees,
    demand: demandFor(),
    events: [{ id: 'ev1', kind: 'truck', day: 2, start: OPEN - 60, end: 15 * 60, note: 'Weekly truck' }],
    budget: { weekly_hours_cap: 520, weekly_dollar_cap: null, overtime_allowed: false, approvals: [] },
    constraints: [],
    unmodeled: [],
    law_pack: null,
  }
}
