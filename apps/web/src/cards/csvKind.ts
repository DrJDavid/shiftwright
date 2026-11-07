import type { CsvImportKind, ImportPreview } from '../api/protocol'

/** Best guess of a dropped file's kind from its name; the card lets the leader change it. */
export function guessKind(fileName: string): CsvImportKind {
  const n = fileName.toLowerCase()
  if (/train|skill|cert/.test(n)) return 'training'
  if (/avail/.test(n)) return 'availability'
  if (/forecast|workload|demand/.test(n)) return 'forecast'
  if (/hist|punch|past/.test(n)) return 'history'
  return 'roster'
}

/**
 * Required fields still unmapped (v1.4: from `required_any_of`; older servers: the fallback below) under the current (edited) mapping. Mirrors apps/api imports.unmapped_required,
 * including its alternatives: roster `name` is satisfied by first_name + last_name, roster age by `age` or
 * `birth_date`, and availability needs at least one avail_* column.
 */
export function missingFields(kind: CsvImportKind, preview: ImportPreview, mapping: Record<string, string | null>): string[] {
  const mapped = new Set(Object.values(mapping).filter((v): v is string => !!v))
  // v1.4: the server states the alternatives itself.
  if (preview.required_any_of?.length)
    return preview.required_any_of.filter((r) => !r.any_of.some((alt) => alt.every((f) => mapped.has(f)))).map((r) => r.need)
  const required = preview.required_fields?.length ? preview.required_fields : preview.unmapped_required
  const missing = required.filter((f) => !mapped.has(f) && f !== 'age' && f !== 'avail_mon..avail_sun')
  if (kind === 'roster') {
    const i = missing.indexOf('name')
    if (i >= 0 && mapped.has('first_name') && mapped.has('last_name')) missing.splice(i, 1)
    if (!mapped.has('age') && !mapped.has('birth_date')) missing.push('age')
  }
  if (kind === 'availability' && ![...mapped].some((v) => v.startsWith('avail_'))) missing.push('avail_mon..avail_sun')
  return missing
}
