import { describe, expect, it } from 'vitest'
import { guessKind, missingFields } from './csvKind'
import { slug, uniqueId } from './ids'
import { fromHHMM, toHHMM } from './time'

describe('card helpers', () => {
  it('guesses the CSV kind from the file name', () => {
    expect(guessKind('roster.csv')).toBe('roster')
    expect(guessKind('Training_Export.csv')).toBe('training')
    expect(guessKind('availability.csv')).toBe('availability')
    expect(guessKind('forecast.csv')).toBe('forecast')
    expect(guessKind('history.csv')).toBe('history')
  })
  it('makes unique slugs', () => {
    expect(slug('Truck Unload!')).toBe('truck_unload')
    expect(uniqueId(['cashier', 'cashier_2'], 'cashier')).toBe('cashier_3')
  })
  it('round-trips times', () => {
    expect(toHHMM(390)).toBe('06:30')
    expect(fromHHMM('22:15')).toBe(1335)
  })
})

describe('csv import required fields', () => {
  const pv = (kind: string, required: string[]) =>
    ({ kind, columns: [], proposed_mapping: {}, unmapped_required: [], rows_preview: [], row_count: 0, warnings: [], target_fields: [], required_fields: required })
  it('accepts birth date for age and first + last for name', () => {
    const req = ['employee_id', 'name', 'home_department', 'wage_per_hour']
    const m = { ID: 'employee_id', First: 'first_name', Last: 'last_name', Dept: 'home_department', Rate: 'wage_per_hour', DOB: 'birth_date' }
    expect(missingFields('roster', pv('roster', req), m)).toEqual([])
    expect(missingFields('roster', pv('roster', req), { ...m, DOB: null })).toEqual(['age'])
    expect(missingFields('roster', pv('roster', req), { ...m, Last: null })).toEqual(['name'])
  })
  it('availability needs one day column', () => {
    expect(missingFields('availability', pv('availability', ['employee_id']), { ID: 'employee_id' })).toEqual(['avail_mon..avail_sun'])
    expect(missingFields('availability', pv('availability', ['employee_id']), { ID: 'employee_id', Mon: 'avail_mon' })).toEqual([])
  })
})
