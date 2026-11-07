import { useEffect, useMemo, useRef, useState } from 'react'
import type { Api } from '../api/client'
import type { CardType, ChatEvent, ChatMode } from '../api/protocol'
import { ChatCard } from '../cards'
import type { CardStatus } from '../cards/CardFrame'
import { CardEnvContext } from '../cards/context'
import { guessKind } from '../cards/csvKind'

type Item =
  | { kind: 'user'; id: number; text: string }
  | { kind: 'assistant'; id: number; text: string }
  | {
      kind: 'card'
      id: number
      cardId: string
      cardType: CardType
      props: unknown
      status: CardStatus
      result?: unknown
      /** Opened by the web (file drop), not by the agent: never POSTed to /chat/card. */
      local?: { file: File }
    }
  | { kind: 'error'; id: number; text: string }

type NewItem = Item extends infer T ? (T extends Item ? Omit<T, 'id'> : never) : never

type Props = {
  api: Api
  storeId: string
  mode: ChatMode
  onConfigChanged: () => void
  /** A tool in the chat turn produced a new schedule (e.g. the agent ran a solve). */
  onScheduleChanged: () => void
  /** Collapse the chat column (e.g. to give the Store tab room). */
  onHide?: () => void
}

const STARTERS = ['Set up my store', 'Build the schedule']

export function ChatPane({ api, storeId, mode, onConfigChanged, onScheduleChanged, onHide }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const env = useMemo(() => ({ api, storeId, onConfigChanged }), [api, storeId, onConfigChanged])
  const seq = useRef(0)
  const scroller = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  // The live API sends one `text` event per LLM step; a tool call between them starts a new bubble.
  const newBubble = useRef(true)

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [items, activity])

  const push = (it: NewItem) => setItems((xs) => [...xs, { ...it, id: ++seq.current } as Item])

  const handle = (ev: ChatEvent) => {
    switch (ev.event) {
      case 'text': {
        const fresh = newBubble.current
        newBubble.current = false
        setItems((xs) => {
          const last = xs.at(-1)
          if (!fresh && last?.kind === 'assistant')
            return [...xs.slice(0, -1), { ...last, text: last.text ? last.text + ev.data.delta : ev.data.delta.replace(/^\s+/, '') }]
          return [...xs, { kind: 'assistant', id: ++seq.current, text: ev.data.delta.replace(/^\s+/, '') }]
        })
        break
      }
      case 'card':
        push({
          kind: 'card',
          cardId: ev.data.card_id,
          cardType: ev.data.card_type,
          props: ev.data.props,
          status: 'open',
        })
        break
      case 'config':
        onConfigChanged()
        break
      case 'tool':
        newBubble.current = true
        setActivity(ev.data.status === 'start' ? `${humanize(ev.data.summary)}…` : humanize(ev.data.summary))
        if (ev.data.status === 'done' && /solve|fix/.test(ev.data.name)) onScheduleChanged()
        break
      case 'error':
        push({ kind: 'error', text: ev.data.message })
        break
      case 'done':
        break
    }
  }

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || busy) return
    setDraft('')
    push({ kind: 'user', text: content })
    newBubble.current = true
    setBusy(true)
    setActivity(null)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await api.chat(storeId, { mode, messages: [{ role: 'user', content }] }, handle, ctrl.signal)
    } catch (err) {
      if (!ctrl.signal.aborted)
        push({
          kind: 'error',
          text: `Chat connection failed: ${(err as Error).message}`,
        })
    } finally {
      setBusy(false)
    }
  }

  const setCard = (cardId: string, patch: Partial<Extract<Item, { kind: 'card' }>>) =>
    setItems((xs) => xs.map((x) => (x.kind === 'card' && x.cardId === cardId ? { ...x, ...patch } : x)))

  const onDrop = (files: FileList | null) => {
    const file = [...(files ?? [])].find((f) => /\.csv$/i.test(f.name) || f.type === 'text/csv')
    if (!file) {
      push({ kind: 'error', text: 'Drop a .csv file to import it.' })
      return
    }
    push({
      kind: 'card',
      cardId: `local-${seq.current + 1}`,
      cardType: 'csv_import',
      props: { kind: guessKind(file.name) },
      status: 'open',
      local: { file },
    })
  }

  const submitCard = async (cardId: string, result: unknown, cancelled = false) => {
    const item = items.find((x) => x.kind === 'card' && x.cardId === cardId)
    if (item?.kind === 'card' && item.local) {
      setCard(cardId, {
        status: cancelled ? 'cancelled' : 'submitted',
        result,
      })
      const r = result as { committed?: boolean; rows?: number } | null
      if (!cancelled && r?.committed && !busy) void send(`I imported ${item.local.file.name} (${r.rows ?? 0} rows).`)
      return
    }
    setCard(cardId, { status: 'submitting' })
    try {
      await api.submitCard(storeId, {
        card_id: cardId,
        result: cancelled ? { cancelled: true } : result,
      })
      setCard(cardId, {
        status: cancelled ? 'cancelled' : 'submitted',
        result,
      })
    } catch (err) {
      setCard(cardId, { status: 'open' })
      push({
        kind: 'error',
        text: `Couldn't save that card: ${(err as Error).message}`,
      })
    }
  }

  return (
    <CardEnvContext.Provider value={env}>
      <section
        className="relative flex min-h-0 flex-col border-r border-rule bg-paper"
        aria-label="Chat"
        onDragOver={(e) => {
          if ([...e.dataTransfer.types].includes('Files')) {
            e.preventDefault()
            setDragging(true)
          }
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          onDrop(e.dataTransfer.files)
        }}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-pine bg-pine-wash/90 text-lg font-semibold text-pine-dark">
            Drop a CSV to import it
          </div>
        )}
        <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {items.length === 0 && (
            <div className="pt-6">
              <h2 className="text-lg font-semibold">Tell me about your store</h2>
              <p className="mt-1 text-ink-2">
                I'll ask for what the schedule needs, one step at a time. You can also type rules in your own words, like "Jordan and Casey
                shouldn't close together." Drop a CSV export here to import it.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void send(s)}
                    className="rounded-full border border-ink/25 bg-panel px-3.5 py-1.5 text-sm font-medium hover:border-ink"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {items.map((it) => {
            if (it.kind === 'user')
              return (
                <div key={it.id} className="ml-10 rounded-lg bg-ink px-3.5 py-2 text-white">
                  {it.text}
                </div>
              )
            if (it.kind === 'assistant' && !it.text) return null
            if (it.kind === 'assistant')
              return (
                <p key={it.id} className="max-w-[60ch] leading-relaxed whitespace-pre-wrap">
                  {it.text}
                </p>
              )
            if (it.kind === 'error')
              return (
                <p key={it.id} role="alert" className="rounded-md border border-gap/30 bg-gap-wash px-3 py-2 text-sm text-gap">
                  {it.text}
                </p>
              )
            return (
              <ChatCard
                key={it.id}
                cardId={it.cardId}
                cardType={it.cardType}
                props={it.props}
                status={it.status}
                result={it.result}
                initialFile={it.local?.file}
                onSubmit={(r) => void submitCard(it.cardId, r)}
                onCancel={() => void submitCard(it.cardId, null, true)}
              />
            )
          })}
          {busy && !items.some((x) => x.kind === 'card' && x.status !== 'submitted' && x.status !== 'cancelled') && (
            <div className="h-4 w-10 animate-pulse rounded bg-rule" aria-label="Assistant is responding" />
          )}
        </div>

        <div className="border-t border-rule bg-panel px-3 pt-2 pb-3">
          <div className="flex h-5 items-center gap-2 text-xs text-muted">
            <span className="min-w-0 flex-1 truncate" aria-live="polite">
              {activity ?? ''}
            </span>
            {onHide && (
              <button type="button" onClick={onHide} className="shrink-0 hover:text-ink" title="Hide the chat">
                Hide chat
              </button>
            )}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void send(draft)
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={busy ? 'Waiting for the current step…' : 'Message Shiftwright'}
              disabled={busy}
              aria-label="Message"
              className="min-w-0 flex-1 rounded-md border border-rule bg-panel px-3 py-2 focus:border-pine focus:outline-none focus:ring-2 focus:ring-pine/20 disabled:bg-paper"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="rounded-md bg-ink px-4 py-2 font-semibold text-white disabled:opacity-40"
            >
              Send
            </button>
          </form>
        </div>
      </section>
    </CardEnvContext.Provider>
  )
}

/** Tool names arrive as identifiers ("ask_payroll", "Ran readiness_check"); make them readable. */
function humanize(s: string): string {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}
