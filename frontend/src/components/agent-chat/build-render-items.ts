import type { AgentSSEEvent } from './types'

// ─── RenderItem types ──────────────────────────────────────────────────────
//
// The pure projection layer between raw SSE events and the renderer. Lives
// in its own module so ChatHistory.tsx can stay component-only (Vite Fast
// Refresh requires a `.tsx` file to export only React components).

export type RenderKind =
  | 'user_message'
  | 'assistant_text'
  | 'node'
  | 'tool_call'
  | 'applied_change'
  | 'compaction'
  | 'budget_warning'
  | 'requires_choice'
  | 'error'
  | 'usage'

export interface RenderItem {
  kind: RenderKind
  // Item-specific payload — narrowed inside the renderer switch.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any
  /** When `kind === 'tool_call'`, this holds the matching tool_result
   *  payload (or undefined while the tool is still pending). */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pairedToolResult?: any
}

// ─── buildRenderItems ──────────────────────────────────────────────────────
//
// Walks the events array once and emits a flat list of RenderItems:
//
//   * Sequential `token` events collapse into a single `assistant_text`
//     block. Any non-token event "closes" that block, so the next token
//     starts a new one.
//   * `tool_call` is recorded with its id; `tool_result` with the same id
//     attaches as `pairedToolResult` to the existing card. Orphan results
//     (no matching call) get their own card so they're still visible.
//   * Heartbeat / lifecycle events (`session`, `done`, `cancelled`,
//     `view_change`, `budget_exhausted`, `ping`) are dropped — the status
//     bar + connection UI handle those concerns.
//   * Consecutive duplicate `node` events collapse so the user doesn't
//     see "Planning…" three times in a row.

export function buildRenderItems(events: AgentSSEEvent[]): RenderItem[] {
  const items: RenderItem[] = []
  const toolCallIndex = new Map<string, number>()
  let openTextIdx: number | null = null

  for (const evt of events) {
    const payload = (evt.payload ?? {}) as Record<string, unknown>

    if (evt.kind !== 'token') openTextIdx = null

    switch (evt.kind) {
      case 'session':
      case 'done':
      case 'cancelled':
      case 'view_change':
      case 'budget_exhausted':
      case 'ping':
        break

      case 'message': {
        const role = (payload.role as string | undefined) ?? 'assistant'
        const text =
          (payload.text as string | undefined) ?? (payload.final as string | undefined) ?? ''
        if (!text) break
        if (role === 'user') {
          items.push({ kind: 'user_message', payload: { text } })
        } else {
          items.push({ kind: 'assistant_text', payload: { text } })
        }
        break
      }

      case 'token': {
        const delta = (payload.delta as string | undefined) ?? ''
        if (!delta) break
        if (openTextIdx === null) {
          openTextIdx = items.length
          items.push({ kind: 'assistant_text', payload: { text: delta } })
        } else {
          items[openTextIdx].payload.text += delta
        }
        break
      }

      case 'node': {
        const name = (payload.name as string | undefined) ?? ''
        if (!name) break
        const last = items[items.length - 1]
        if (last && last.kind === 'node' && last.payload?.node === name) break
        items.push({ kind: 'node', payload: { node: name } })
        break
      }

      case 'tool_call': {
        const id = (payload.id as string | undefined) ?? `_anon_${items.length}`
        const item: RenderItem = {
          kind: 'tool_call',
          payload: {
            id,
            name: payload.name as string,
            args: payload.args,
          },
        }
        toolCallIndex.set(id, items.length)
        items.push(item)
        break
      }

      case 'tool_result': {
        const id = payload.id as string | undefined
        const idx = id != null ? toolCallIndex.get(id) : undefined
        if (idx == null) {
          items.push({
            kind: 'tool_call',
            payload: { id: id ?? '_orphan', name: '?', args: {} },
            pairedToolResult: payload,
          })
        } else {
          items[idx].pairedToolResult = payload
        }
        break
      }

      case 'applied_change':
        items.push({ kind: 'applied_change', payload })
        break

      case 'compaction_applied':
        items.push({ kind: 'compaction', payload })
        break

      case 'budget_warning':
        items.push({ kind: 'budget_warning', payload })
        break

      case 'requires_choice':
        items.push({ kind: 'requires_choice', payload })
        break

      case 'error':
        items.push({ kind: 'error', payload })
        break

      case 'usage':
        items.push({ kind: 'usage', payload })
        break
    }
  }

  return items
}
