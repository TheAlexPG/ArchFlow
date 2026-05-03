export type ContextKind = 'workspace' | 'diagram' | 'object' | 'none'

export interface ChatContext {
  kind: ContextKind
  id?: string
  draft_id?: string
  parent_diagram_id?: string
}

// ─── Streaming event protocol (spec §3.7) ──────────────────────────────────
//
// Every kind the backend can emit on /api/v1/agents/{id}/chat or on a
// resumed stream via /api/v1/agents/sessions/{id}/stream. The string values
// match the SSE `event:` line exactly; the `payload` shape is per-kind and
// intentionally typed as `unknown` here — render components downcast it
// using their own narrowed schemas.

export type AgentSSEEventKind =
  | 'session'
  | 'node'
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'message'
  | 'budget_warning'
  | 'budget_exhausted'
  | 'compaction_applied'
  | 'applied_change'
  | 'requires_choice'
  | 'view_change'
  | 'cancelled'
  | 'usage'
  | 'done'
  | 'error'
  | 'ping'

export interface AgentSSEEvent {
  /** Monotonic per-session sequence id; used as Last-Event-ID on reconnect. */
  id: number
  kind: AgentSSEEventKind
  payload: unknown
}

// ─── Invoke request body (spec §5.4) ───────────────────────────────────────

export type ChatMode = 'full' | 'read_only'

export interface AgentInvokeBody {
  /** Omit to start a new session; backend will assign one and emit
   *  `event: session` as the first frame. */
  session_id?: string
  context: ChatContext
  message: string
  mode: ChatMode
  metadata?: Record<string, unknown>
}
