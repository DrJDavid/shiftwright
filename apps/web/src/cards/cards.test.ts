import { describe, expect, it } from 'vitest'
import { guessKind } from './csvKind'
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
