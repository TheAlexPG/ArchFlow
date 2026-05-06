import type { AgentSessionMessage } from './hooks/use-agent-sessions'
import type { AgentSSEEvent } from './types'

// ─── seedEventsFromMessages ────────────────────────────────────────────────
//
// Convert persisted ``AgentChatMessage`` rows (as exposed via
// ``GET /agents/sessions/:id``) into the same shape the SSE stream emits at
// runtime. ``ChatBubble`` calls this when the user opens an old chat — the
// resulting events are seeded into the stream's ``events`` array, so
// ``buildRenderItems`` produces ToolCallCard / NodeIndicator items the same
// way it does for a live session.
//
// Mapping:
//   * user           → `message` (role=user, text=content_text)
//   * assistant text → `message` (role=assistant, text=content_text)
//   * assistant w/ tool_calls (no content_text) → one `tool_call` event per
//                     call, taking id/name/arguments from content_json
//   * tool result    → `tool_result` event keyed by tool_call_id; status is
//                     not persisted, so we render as ``ok`` (rerunning the
//                     pairing logic in build-render-items.ts)
//   * system_summary / system / compacted rows → skipped
//
// Node-transition events (`node`) are NOT reconstructable from the DB —
// they're live graph signals. ToolCallCard already shows the tool name, so
// the per-tool icon row is enough; we accept losing the "Planning…" /
// "Researcher" badges between sessions.

interface OpenAiToolCall {
  id?: string
  type?: string
  function?: {
    name?: string
    arguments?: string
  }
}

const PREVIEW_LEN = 120

export function seedEventsFromMessages(
  messages: AgentSessionMessage[],
): Array<Pick<AgentSSEEvent, 'kind' | 'payload'>> {
  const out: Array<Pick<AgentSSEEvent, 'kind' | 'payload'>> = []

  for (const m of messages) {
    if (m.is_compacted) continue

    if (m.role === 'user') {
      const text = (m.content_text ?? '').trim()
      if (text) {
        out.push({ kind: 'message', payload: { role: 'user', text } })
      }
      continue
    }

    if (m.role === 'assistant') {
      // Plain assistant text — preserve as a regular message bubble.
      const text = (m.content_text ?? '').trim()
      if (text) {
        out.push({ kind: 'message', payload: { role: 'assistant', text } })
        continue
      }
      // Assistant turn with tool_calls — runtime persists the entire OpenAI-
      // shape message into ``content_json`` when ``content`` is null.
      const json = m.content_json ?? {}
      const toolCalls = Array.isArray(json.tool_calls)
        ? (json.tool_calls as OpenAiToolCall[])
        : []
      for (const tc of toolCalls) {
        const fn = tc.function ?? {}
        out.push({
          kind: 'tool_call',
          payload: {
            id: tc.id ?? '',
            name: fn.name ?? '?',
            args: fn.arguments ?? '',
          },
        })
      }
      continue
    }

    if (m.role === 'tool') {
      const text = (m.content_text ?? '').trim()
      out.push({
        kind: 'tool_result',
        payload: {
          id: m.tool_call_id ?? '',
          status: 'ok',
          preview: text.slice(0, PREVIEW_LEN),
          content: text,
        },
      })
      continue
    }
    // role === 'system' / 'system_summary' — skip; LLM-context only.
  }

  return out
}
