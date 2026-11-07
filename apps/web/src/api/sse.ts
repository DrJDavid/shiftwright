// Minimal Server-Sent Events reader over a fetch() body (EventSource can't POST).

export type RawSSE = { event: string; data: unknown }

export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (e: RawSSE) => void,
): Promise<void> {
  const reader = body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  const flush = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue
      const i = line.indexOf(':')
      const field = i === -1 ? line : line.slice(0, i)
      const value = i === -1 ? '' : line.slice(i + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length === 0) return
    const text = data.join('\n')
    let parsed: unknown = text
    try {
      parsed = JSON.parse(text)
    } catch {
      /* keep raw text */
    }
    onEvent({ event, data: parsed })
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (value) buf += dec.decode(value, { stream: true })
    buf = buf.replace(/\r\n?/g, '\n')
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      flush(buf.slice(0, idx))
      buf = buf.slice(idx + 2)
    }
    if (done) break
  }
  if (buf.trim()) flush(buf)
}
