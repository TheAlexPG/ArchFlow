import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AgentStreamError,
  cancelAgentSession,
  reconnectAgent,
  respondToChoice,
  streamAgent,
} from '../agent-stream'
import type { AgentSSEEvent } from '../../components/agent-chat/types'

// ─── Helpers ────────────────────────────────────────────────────────────────
//
// We stub `globalThis.fetch` per-test. Each test builds a Response object
// whose body is a ReadableStream that yields the SSE frames the server
// would have sent. Vitest 3 + jsdom expose ReadableStream natively so no
// polyfill is needed.

function makeReadableStream(chunks: string[], opts?: { error?: Error }): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream<Uint8Array>({
    async pull(ctrl) {
      if (opts?.error) {
        ctrl.error(opts.error)
        return
      }
      if (i >= chunks.length) {
        ctrl.close()
        return
      }
      ctrl.enqueue(encoder.encode(chunks[i]))
      i += 1
    },
  })
}

function makeSSEResponse(chunks: string[], status = 200): Response {
  return new Response(makeReadableStream(chunks), {
    status,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function buildEventFrame(kind: string, id: number, data: unknown): string {
  return `event: ${kind}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`
}

// ─── Suite ──────────────────────────────────────────────────────────────────

describe('streamAgent', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('parses a single session event and delivers it to onEvent', async () => {
    fetchMock.mockResolvedValue(
      makeSSEResponse([buildEventFrame('session', 1, { session_id: 'sess-abc' })]),
    )
    const events: AgentSSEEvent[] = []
    const onClose = vi.fn()

    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'workspace', id: 'ws-1' }, message: 'hi', mode: 'full' },
      onEvent: (e) => events.push(e),
      onClose,
    })

    expect(events).toHaveLength(1)
    expect(events[0]).toEqual({
      id: 1,
      kind: 'session',
      payload: { session_id: 'sess-abc' },
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('parses a multi-event stream split across chunks', async () => {
    // Split a frame across two chunks to make sure the buffer joins them.
    const chunk1 = 'event: session\nid: 1\ndata: {"session_id":"s1"}\n\nevent: token\nid: 2\nda'
    const chunk2 = 'ta: {"delta":"Hel"}\n\nevent: token\nid: 3\ndata: {"delta":"lo"}\n\n'
    fetchMock.mockResolvedValue(makeSSEResponse([chunk1, chunk2]))

    const events: AgentSSEEvent[] = []
    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'workspace', id: 'w' }, message: 'x', mode: 'read_only' },
      onEvent: (e) => events.push(e),
    })

    expect(events.map((e) => e.kind)).toEqual(['session', 'token', 'token'])
    expect(events[1].payload).toEqual({ delta: 'Hel' })
    expect(events[2].payload).toEqual({ delta: 'lo' })
  })

  it('treats event: done as a natural close (onClose, not onError)', async () => {
    fetchMock.mockResolvedValue(
      makeSSEResponse([
        buildEventFrame('session', 1, { session_id: 's' }),
        buildEventFrame('done', 2, { final: 'ok' }),
        // Server sometimes keeps the stream open briefly — we should
        // stop reading after 'done' regardless.
        buildEventFrame('token', 3, { delta: 'late' }),
      ]),
    )

    const events: AgentSSEEvent[] = []
    const onError = vi.fn()
    const onClose = vi.fn()
    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'none' }, message: '', mode: 'full' },
      onEvent: (e) => events.push(e),
      onError,
      onClose,
    })

    expect(events.map((e) => e.kind)).toEqual(['session', 'done'])
    expect(onError).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('AbortSignal pre-aborted: skips fetch entirely and calls onClose', async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    const onClose = vi.fn()

    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'none' }, message: '', mode: 'full' },
      signal: ctrl.signal,
      onEvent: vi.fn(),
      onClose,
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('AbortSignal during stream: cancels reader and calls onClose without onError', async () => {
    const ctrl = new AbortController()

    // Server streams slowly — we abort after the first event.
    const pendingPull: { resolve: (() => void) | null } = { resolve: null }
    const slowBody = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder()
        controller.enqueue(enc.encode(buildEventFrame('session', 1, { session_id: 'x' })))
      },
      pull() {
        return new Promise<void>((resolve) => {
          pendingPull.resolve = resolve
        })
      },
    })
    fetchMock.mockResolvedValue(
      new Response(slowBody, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    )

    const onError = vi.fn()
    const onClose = vi.fn()
    const events: AgentSSEEvent[] = []

    const streamPromise = streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'none' }, message: '', mode: 'full' },
      signal: ctrl.signal,
      onEvent: (e) => {
        events.push(e)
        // Abort after the first event arrives.
        ctrl.abort()
      },
      onError,
      onClose,
    })

    // Allow the abort listener to cancel the reader.
    await new Promise((r) => setTimeout(r, 5))
    pendingPull.resolve?.()
    await streamPromise

    expect(events).toHaveLength(1)
    expect(onError).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('network error before headers: onError called with network code', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const onError = vi.fn()
    const onClose = vi.fn()

    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'none' }, message: '', mode: 'full' },
      onEvent: vi.fn(),
      onError,
      onClose,
    })

    expect(onError).toHaveBeenCalledTimes(1)
    const err = onError.mock.calls[0][0] as AgentStreamError
    expect(err).toBeInstanceOf(AgentStreamError)
    expect(err.code).toBe('network')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('event: error inside the stream is delivered to onEvent (not onError)', async () => {
    // Spec: HTTP status stays 200 once stream started; runtime errors are
    // SSE events, not transport errors.
    fetchMock.mockResolvedValue(
      makeSSEResponse([
        buildEventFrame('session', 1, { session_id: 's' }),
        buildEventFrame('error', 2, { code: 'budget_exhausted', message: 'no $ left' }),
        buildEventFrame('done', 3, {}),
      ]),
    )
    const events: AgentSSEEvent[] = []
    const onError = vi.fn()

    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'none' }, message: '', mode: 'full' },
      onEvent: (e) => events.push(e),
      onError,
    })

    expect(events.map((e) => e.kind)).toEqual(['session', 'error', 'done'])
    expect(events[1].payload).toEqual({ code: 'budget_exhausted', message: 'no $ left' })
    expect(onError).not.toHaveBeenCalled()
  })

  it('sends Authorization + X-Workspace-ID headers when supplied', async () => {
    fetchMock.mockResolvedValue(makeSSEResponse([buildEventFrame('done', 1, {})]))

    await streamAgent({
      url: '/api/v1/agents/general/chat',
      body: { context: { kind: 'workspace', id: 'w' }, message: 'x', mode: 'full' },
      authToken: 'jwt-xyz',
      workspaceId: 'ws-42',
      onEvent: vi.fn(),
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.headers).toMatchObject({
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      Authorization: 'Bearer jwt-xyz',
      'X-Workspace-ID': 'ws-42',
    })
  })
})

// ─── cancelAgentSession ─────────────────────────────────────────────────────

describe('cancelAgentSession', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('POSTs to /sessions/{id}/cancel', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }))

    await cancelAgentSession('sess-99', 'jwt-x', 'ws-1')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/agents/sessions/sess-99/cancel')
    expect((init as RequestInit).method).toBe('POST')
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: 'Bearer jwt-x',
      'X-Workspace-ID': 'ws-1',
    })
  })

  it('throws AgentStreamError on non-OK response', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 404 }))
    await expect(cancelAgentSession('sess-x')).rejects.toBeInstanceOf(AgentStreamError)
  })
})

// ─── respondToChoice ────────────────────────────────────────────────────────

describe('respondToChoice', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('POSTs to /sessions/{id}/respond with the choice body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }))

    await respondToChoice(
      'sess-1',
      { tool_call_id: 'tc-7', choice_id: 'create_draft', extra: { name: 'My Draft' } },
      'tok',
      'ws-2',
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/agents/sessions/sess-1/respond')
    expect((init as RequestInit).method).toBe('POST')
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({
      tool_call_id: 'tc-7',
      choice_id: 'create_draft',
      extra: { name: 'My Draft' },
    })
  })
})

// ─── reconnectAgent ─────────────────────────────────────────────────────────

describe('reconnectAgent', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses GET with Last-Event-ID header and since query param', async () => {
    fetchMock.mockResolvedValue(makeSSEResponse([buildEventFrame('done', 12, {})]))

    await reconnectAgent({
      sessionId: 'sess-5',
      sinceId: 11,
      authToken: 't',
      onEvent: vi.fn(),
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/agents/sessions/sess-5/stream?since=11')
    expect((init as RequestInit).method).toBe('GET')
    expect((init as RequestInit).headers).toMatchObject({
      'Last-Event-ID': '11',
      Authorization: 'Bearer t',
    })
  })

  it('410 on reconnect → onError with code expired', async () => {
    fetchMock.mockResolvedValue(new Response('gone', { status: 410 }))
    const onError = vi.fn()
    const onClose = vi.fn()

    await reconnectAgent({
      sessionId: 'sess-x',
      sinceId: 5,
      onEvent: vi.fn(),
      onError,
      onClose,
    })

    expect(onError).toHaveBeenCalledTimes(1)
    const err = onError.mock.calls[0][0] as AgentStreamError
    expect(err.code).toBe('expired')
    expect(err.status).toBe(410)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
