import { describe, expect, it } from 'vitest'
import { readSSE } from './sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch))
      c.close()
    },
  })
}

describe('readSSE', () => {
  it('parses events split across chunk boundaries', async () => {
    const got: { event: string; data: unknown }[] = []
    await readSSE(
      streamOf(['event: text\ndata: {"del', 'ta":"Hi"}\n\n', 'event: done\r\ndata: {}\r\n\r\n']),
      (e) => got.push(e),
    )
    expect(got).toEqual([
      { event: 'text', data: { delta: 'Hi' } },
      { event: 'done', data: {} },
    ])
  })
  it('defaults the event name to "message" and joins multi-line data', async () => {
    const got: { event: string; data: unknown }[] = []
    await readSSE(streamOf(['data: {"a":\ndata: 1}\n\n']), (e) => got.push(e))
    expect(got).toEqual([{ event: 'message', data: { a: 1 } }])
  })
})
