import { useEffect, useId, useRef, useState } from 'react'
import type { CsvImportKind, CsvImportProps, CsvImportResult, ImportPreview } from '../api/protocol'
import { CardFrame, inputCls, type CardProps } from './CardFrame'
import { useCardEnv } from './context'

const KIND_LABEL: Record<CsvImportKind, string> = {
  roster: 'Roster',
  training: 'Training',
  availability: 'Availability',
  forecast: 'Workload forecast',
  history: 'Past schedules',
}

/** Field names apps/api accepts per kind (imports.TARGETS). Shown as mapping choices. */
const TARGETS: Record<CsvImportKind, string[]> = {
  roster: ['employee_id', 'name', 'first_name', 'last_name', 'phone', 'age', 'birth_date', 'home_department', 'status', 'wage_per_hour', 'hire_date', 'min_hours_week', 'max_hours_week', 'trained_roles'],
  training: ['employee_id', 'role'],
  availability: ['employee_id', 'avail_mon', 'avail_tue', 'avail_wed', 'avail_thu', 'avail_fri', 'avail_sat', 'avail_sun', 'note'],
  forecast: ['role', 'day', 'start', 'end', 'headcount'],
  history: ['employee_id', 'date', 'start', 'end', 'role'],
}


type Props = CardProps<CsvImportProps, CsvImportResult> & { initialFile?: File }

export function CsvImportCard({ props, status, result, onSubmit, onCancel, initialFile }: Props) {
  const formId = useId()
  const env = useCardEnv()
  const [kind, setKind] = useState<CsvImportKind>(props?.kind ?? 'roster')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(props?.preview ?? null)
  const [mapping, setMapping] = useState<Record<string, string | null>>(props?.preview?.proposed_mapping ?? {})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const started = useRef(false)

  const upload = async (f: File, k: CsvImportKind) => {
    setFile(f)
    setBusy('Reading the file…')
    setError(null)
    try {
      const pv = await env.api.importPreview(env.storeId, k, f)
      setPreview(pv)
      setMapping(pv.proposed_mapping)
    } catch (e) {
      setError((e as Error).message)
      setPreview(null)
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    if (initialFile && !started.current && status === 'open') {
      started.current = true
      void upload(initialFile, kind)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once for a dropped file
  }, [initialFile])

  const mapped = new Set(Object.values(mapping).filter(Boolean))
  const missing = preview ? preview.unmapped_required.filter((f) => !mapped.has(f)) : []
  const canCommit = !!preview && !busy && missing.length === 0

  const commit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!preview || !canCommit) return
    setBusy('Saving…')
    setError(null)
    try {
      await env.api.importCommit(env.storeId, kind, mapping, preview.rows_preview)
      env.onConfigChanged()
      onSubmit({ committed: true, rows: preview.row_count })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const summary = status === 'submitted' && result ? `${KIND_LABEL[kind]}: imported ${result.rows} rows${file ? ` from ${file.name}` : ''}.` : null
  const cols = preview?.columns ?? []
  const options = [...new Set([...TARGETS[kind], ...Object.values(mapping).filter((v): v is string => !!v)])]

  return (
    <CardFrame title={`Import ${KIND_LABEL[kind].toLowerCase()} CSV`} status={status} summary={summary} onCancel={onCancel} submitLabel="Import" canSubmit={canCommit} formId={formId}>
      <form id={formId} onSubmit={(e) => void commit(e)} className="space-y-2.5">
        <div className="flex gap-2">
          <select
            className={`${inputCls} w-36 shrink-0`}
            aria-label="What's in the file"
            value={kind}
            onChange={(e) => {
              const k = e.target.value as CsvImportKind
              setKind(k)
              if (file) void upload(file, k)
            }}
          >
            {(Object.keys(KIND_LABEL) as CsvImportKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => inputRef.current?.click()} className="min-w-0 flex-1 truncate rounded-md border border-dashed border-ink/40 px-3 text-sm font-medium hover:border-ink">
            {file ? file.name : 'Choose a CSV file'}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void upload(f, kind)
            }}
          />
        </div>
        {busy && <p className="text-sm text-muted">{busy}</p>}
        {error && <p className="text-sm text-gap">{error}</p>}
        {preview && (
          <>
            <p className="text-sm text-ink-2">
              {preview.row_count} rows. Check how each column maps; nothing is saved until you import.
            </p>
            <div className="max-h-56 overflow-y-auto rounded border border-rule">
              <table className="w-full text-sm">
                <tbody>
                  {cols.map((c) => {
                    const sample = (preview.rows_preview[0] as Record<string, unknown> | undefined)?.[c]
                    return (
                      <tr key={c} className="border-b border-rule-soft last:border-0">
                        <td className="px-2 py-1">
                          <div className="font-medium">{c}</div>
                          {sample != null && <div className="truncate text-xs text-muted">e.g. {String(sample)}</div>}
                        </td>
                        <td className="w-40 px-2 py-1">
                          <select
                            className={`${inputCls} py-1 text-xs`}
                            aria-label={`Map ${c}`}
                            value={mapping[c] ?? ''}
                            onChange={(e) => setMapping((m) => ({ ...m, [c]: e.target.value || null }))}
                          >
                            <option value="">Ignore</option>
                            {options.map((o) => (
                              <option key={o} value={o}>
                                {o.replace(/_/g, ' ')}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {missing.length > 0 && <p className="text-sm text-gap">Still needed: {missing.map((m) => m.replace(/_/g, ' ')).join(', ')}.</p>}
            {preview.warnings.map((w, i) => (
              <p key={i} className="text-xs text-warn">
                {w}
              </p>
            ))}
          </>
        )}
      </form>
    </CardFrame>
  )
}
