// Low-level SSE client for the agent chat protocol (spec §3.7, §5.4, §6.9).
//
// We deliberately do NOT use `EventSource`: the chat endpoint is a POST
// (it carries the user's message + context as a JSON body), and the
// browser-built EventSource only supports GET. Pulling a full polyfill
// (`@microsoft/fetch-event-source` etc.) just for this would be ~10kb of
// dependency for behavior we can hand-roll cleanly in <100 lines, and
// hand-rolling lets us match the project's existing axios auth pattern
// (Bearer JWT + X-Workspace-ID) without bridging through another lib.
//
// Three exported functions cover the full server contract:
//   - streamAgent       — POST /api/v1/agents/{id}/chat   (initial run)
//   - reconnectAgent    — GET  /api/v1/agents/sessions/{id}/stream?since=N
//   - cancelAgentSession / respondToChoice — small POSTs that don't stream

import type {
  AgentInvokeBody,
  AgentSSEEvent,
  AgentSSEEventKind,
} from '../components/agent-chat/types'

// ─── SSE event-kind set (mirrors types.ts) ─────────────────────────────────
//
// Used to defensively coerce unknown server-sent kinds back to a typed value
// without losing them — anything outside the set is delivered as `error` so
// the UI can surface a generic "unknown event" rather than silently drop it.

const KNOWN_EVENT_KINDS: ReadonlySet<AgentSSEEventKind> = new Set<AgentSSEEventKind>([
  'session',
  'node',
  'token',
  'tool_call',
  'tool_result',
  'message',
  'budget_warning',
  'budget_exhausted',
  'compaction_applied',
  'applied_change',
  'requires_choice',
  'view_change',
  'cancelled',
  'usage',
  'done',
  'error',
  'ping',
])

function coerceKind(raw: string | undefined): AgentSSEEventKind {
  if (raw && KNOWN_EVENT_KINDS.has(raw as AgentSSEEventKind)) {
    return raw as AgentSSEEventKind
  }
  return 'error'
}

// ─── Public types ──────────────────────────────────────────────────────────

export interface AgentStreamOptions {
  /** Full URL or path. Pass `/api/v1/agents/{id}/chat` — no base prefix
   *  is added; we want callers to be able to point at a different host
   *  (e.g. for tests). */
  url: string
  body: AgentInvokeBody
  /** When supplied, sent as `Authorization: Bearer <token>`. Pass the
   *  raw token (NOT prefixed with "Bearer "). Omit for cookie-only
   *  flows (server will accept the session cookie instead). */
  authToken?: string
  /** Optional X-Workspace-ID — matches axios interceptor in api-client.ts. */
  workspaceId?: string
  /** Optional Last-Event-ID for resuming — usually not needed on the
   *  initial /chat call, but supported for completeness. */
  lastEventId?: number
  signal?: AbortSignal
  onEvent: (event: AgentSSEEvent) => void
  onError?: (err: Error) => void
  onClose?: () => void
}

export interface ReconnectOptions {
  sessionId: string
  /** Resume after this event id — server replays anything > sinceId from
   *  its 5-min Redis log. */
  sinceId: number
  authToken?: string
  workspaceId?: string
  signal?: AbortSignal
  onEvent: (event: AgentSSEEvent) => void
  onError?: (err: Error) => void
  onClose?: () => void
  /** Override base URL (defaults to '/api/v1'); useful for tests. */
  baseUrl?: string
}

export interface RespondBody {
  tool_call_id: string
  choice_id: string
  extra?: Record<string, unknown>
}

/** Custom error class so callers can branch on `.code` (e.g. UI shows
 *  "Session expired" for `expired`, "Connection lost" for `network`). */
export class AgentStreamError extends Error {
  code: 'expired' | 'network' | 'http' | 'parse' | 'aborted'
  status?: number

  constructor(
    code: AgentStreamError['code'],
    message: string,
    status?: number,
  ) {
    super(message)
    this.name = 'AgentStreamError'
    this.code = code
    this.status = status
  }
}

// ─── Header + URL helpers ──────────────────────────────────────────────────

function buildHeaders(
  authToken: string | undefined,
  workspaceId: string | undefined,
  lastEventId: number | undefined,
  contentType: string | null,
): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
  }
  if (contentType) headers['Content-Type'] = contentType
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  if (workspaceId) headers['X-Workspace-ID'] = workspaceId
  if (lastEventId !== undefined) headers['Last-Event-ID'] = String(lastEventId)
  return headers
}

// ─── SSE frame parser ──────────────────────────────────────────────────────
//
// SSE frames are separated by a blank line ("\n\n" or "\r\n\r\n"). Within
// a frame, each non-empty line is `field: value`. We collect `event`,
// `id`, and `data` fields; anything else (`retry`, comments starting `:`)
// is ignored. Multiple `data:` lines concatenate with "\n" per the SSE
// spec. We feed bytes incrementally because Response.body chunks don't
// align with frame boundaries.

interface ParsedFrame {
  event?: string
  id?: string
  data: string
}

function parseFrame(raw: string): ParsedFrame | null {
  const lines = raw.split(/\r?\n/)
  const frame: ParsedFrame = { data: '' }
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const sep = line.indexOf(':')
    const field = sep === -1 ? line : line.slice(0, sep)
    // SSE: a single space after ":" is part of the field separator, not the value
    let value = sep === -1 ? '' : line.slice(sep + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    switch (field) {
      case 'event':
        frame.event = value
        break
      case 'id':
        frame.id = value
        break
      case 'data':
        dataLines.push(value)
        break
      // 'retry' and unknown fields: ignored on purpose
    }
  }

  if (dataLines.length === 0 && !frame.event && !frame.id) return null
  frame.data = dataLines.join('\n')
  return frame
}

function frameToEvent(frame: ParsedFrame): AgentSSEEvent {
  let payload: unknown = null
  if (frame.data) {
    try {
      payload = JSON.parse(frame.data)
    } catch {
      // Malformed payload — surface as raw string rather than throwing,
      // so a single bad frame can't kill the whole stream.
      payload = { raw: frame.data, _parse_error: true }
    }
  }
  const id = frame.id ? Number(frame.id) : 0
  return {
    id: Number.isFinite(id) ? id : 0,
    kind: coerceKind(frame.event),
    payload,
  }
}

// ─── Core stream pump ──────────────────────────────────────────────────────
//
// Reads `body` (a ReadableStream<Uint8Array>) chunk-by-chunk, decodes UTF-8,
// splits on blank-line boundaries, parses + dispatches each frame.
//
// Resolves naturally when:
//   - the stream ends (server closed the connection),
//   - or a 'done' event is received (treat as a clean close).
//
// Rejects (via onError) on:
//   - network/decoder error,
//   - AbortSignal already aborted before we entered the loop.
//
// The caller's AbortSignal cancels the underlying fetch, which makes the
// reader throw `AbortError` — we swallow it and call onClose.

async function pumpSSE(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal | undefined,
  onEvent: (event: AgentSSEEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  // If the consumer aborts, cancel the reader so the generator wakes up
  // and we can exit promptly.
  const abortListener = () => {
    reader.cancel().catch(() => undefined)
  }
  signal?.addEventListener('abort', abortListener, { once: true })

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Drain whole frames (SSE separator is \n\n; tolerate \r\n\r\n).
      while (true) {
        const sepIdx = findSeparator(buffer)
        if (sepIdx === -1) break
        const rawFrame = buffer.slice(0, sepIdx.start)
        buffer = buffer.slice(sepIdx.end)
        const frame = parseFrame(rawFrame)
        if (!frame) continue
        const evt = frameToEvent(frame)
        onEvent(evt)
        if (evt.kind === 'done') {
          // Spec: 'done' is the natural end-of-stream marker. Stop reading
          // even if the server hasn't closed the TCP side yet.
          await reader.cancel().catch(() => undefined)
          return
        }
      }
    }
    // Flush any trailing buffered frame (unusual — well-formed servers
    // always emit a final "\n\n" — but better to deliver than to drop).
    const tail = buffer.trim()
    if (tail) {
      const frame = parseFrame(tail)
      if (frame) onEvent(frameToEvent(frame))
    }
  } finally {
    signal?.removeEventListener('abort', abortListener)
    try {
      reader.releaseLock()
    } catch {
      // Already released by cancel() — fine.
    }
  }
}

/** Find the next SSE frame boundary (`\n\n` or `\r\n\r\n`) and return both
 *  the cut-point (where the frame ends) and the resume-point (where the
 *  next frame begins). Returns -1 if no boundary is buffered yet. */
function findSeparator(buf: string): { start: number; end: number } | -1 {
  const lf = buf.indexOf('\n\n')
  const crlf = buf.indexOf('\r\n\r\n')
  if (lf === -1 && crlf === -1) return -1
  if (lf === -1) return { start: crlf, end: crlf + 4 }
  if (crlf === -1) return { start: lf, end: lf + 2 }
  // Both exist — pick whichever comes first.
  return lf < crlf ? { start: lf, end: lf + 2 } : { start: crlf, end: crlf + 4 }
}

// ─── streamAgent: initial POST + stream ────────────────────────────────────

export async function streamAgent(opts: AgentStreamOptions): Promise<void> {
  const { url, body, authToken, workspaceId, lastEventId, signal, onEvent, onError, onClose } = opts

  if (signal?.aborted) {
    onClose?.()
    return
  }

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: buildHeaders(authToken, workspaceId, lastEventId, 'application/json'),
      body: JSON.stringify(body),
      signal,
      // Cookie-session auth path: include credentials so the browser
      // sends the session cookie when no Bearer token is configured.
      credentials: 'include',
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      onClose?.()
      return
    }
    onError?.(new AgentStreamError('network', `Network error: ${(err as Error).message}`))
    onClose?.()
    return
  }

  if (!response.ok) {
    onError?.(
      new AgentStreamError(
        response.status === 410 ? 'expired' : 'http',
        `HTTP ${response.status} ${response.statusText}`,
        response.status,
      ),
    )
    onClose?.()
    return
  }
  if (!response.body) {
    onError?.(new AgentStreamError('parse', 'Response had no body'))
    onClose?.()
    return
  }

  try {
    await pumpSSE(response.body, signal, onEvent)
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      // Caller cancelled — that's a clean close, not an error.
      onClose?.()
      return
    }
    onError?.(new AgentStreamError('network', `Stream error: ${(err as Error).message}`))
  }
  onClose?.()
}

// ─── reconnectAgent: GET resume ────────────────────────────────────────────

export async function reconnectAgent(opts: ReconnectOptions): Promise<void> {
  const {
    sessionId,
    sinceId,
    authToken,
    workspaceId,
    signal,
    onEvent,
    onError,
    onClose,
    baseUrl = '/api/v1',
  } = opts

  if (signal?.aborted) {
    onClose?.()
    return
  }

  const url = `${baseUrl}/agents/sessions/${encodeURIComponent(sessionId)}/stream?since=${sinceId}`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: buildHeaders(authToken, workspaceId, sinceId, null),
      signal,
      credentials: 'include',
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      onClose?.()
      return
    }
    onError?.(new AgentStreamError('network', `Network error: ${(err as Error).message}`))
    onClose?.()
    return
  }

  if (response.status === 410) {
    // Server log expired (>5 min after invocation end) — caller should
    // fall back to GET /sessions/{id} for the full transcript.
    onError?.(new AgentStreamError('expired', 'Session log expired', 410))
    onClose?.()
    return
  }
  if (!response.ok) {
    onError?.(
      new AgentStreamError('http', `HTTP ${response.status} ${response.statusText}`, response.status),
    )
    onClose?.()
    return
  }
  if (!response.body) {
    onError?.(new AgentStreamError('parse', 'Response had no body'))
    onClose?.()
    return
  }

  try {
    await pumpSSE(response.body, signal, onEvent)
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      onClose?.()
      return
    }
    onError?.(new AgentStreamError('network', `Stream error: ${(err as Error).message}`))
  }
  onClose?.()
}

// ─── Side-channel POSTs (cancel + respond) ─────────────────────────────────

/** Fire-and-forget cancel: server sets a Redis flag, the next tool tick
 *  observes it, and the still-open SSE stream gets `cancelled` + `done`
 *  events. Returns once the POST resolves; UI should keep listening to
 *  the existing stream for the actual cancellation events. */
export async function cancelAgentSession(
  sessionId: string,
  authToken?: string,
  workspaceId?: string,
  baseUrl: string = '/api/v1',
): Promise<void> {
  const url = `${baseUrl}/agents/sessions/${encodeURIComponent(sessionId)}/cancel`
  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(authToken, workspaceId, undefined, 'application/json'),
    credentials: 'include',
  })
  if (!response.ok) {
    throw new AgentStreamError('http', `Cancel failed: HTTP ${response.status}`, response.status)
  }
}

/** Respond to a `requires_choice` HITL prompt (spec §6.5). Server resumes
 *  the suspended LangGraph run; new events arrive on the same SSE stream. */
export async function respondToChoice(
  sessionId: string,
  body: RespondBody,
  authToken?: string,
  workspaceId?: string,
  baseUrl: string = '/api/v1',
): Promise<void> {
  const url = `${baseUrl}/agents/sessions/${encodeURIComponent(sessionId)}/respond`
  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(authToken, workspaceId, undefined, 'application/json'),
    body: JSON.stringify(body),
    credentials: 'include',
  })
  if (!response.ok) {
    throw new AgentStreamError('http', `Respond failed: HTTP ${response.status}`, response.status)
  }
}
