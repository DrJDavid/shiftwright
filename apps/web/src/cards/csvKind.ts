import type { CsvImportKind } from '../api/protocol'

/** Best guess of a dropped file's kind from its name; the card lets the leader change it. */
export function guessKind(fileName: string): CsvImportKind {
  const n = fileName.toLowerCase()
  if (/train|skill|cert/.test(n)) return 'training'
  if (/avail/.test(n)) return 'availability'
  if (/forecast|workload|demand/.test(n)) return 'forecast'
  if (/hist|punch|past/.test(n)) return 'history'
  return 'roster'
}
