// ─── archflow:// link parsing ────────────────────────────────────────────────
//
// The archflow:// custom scheme lets the AI agent embed navigable deep-links
// inside its markdown responses. The three target types map to:
//
//   archflow://object/{uuid}      → centre canvas on a model object
//   archflow://diagram/{uuid}     → navigate to /diagram/{id}
//   archflow://connection/{uuid}  → centre canvas on a connection / edge

const SCHEME_RE = /^archflow:\/\/(object|diagram|connection)\/([a-f0-9-]{36})$/i

export type ArchflowLinkTarget = 'object' | 'diagram' | 'connection'

export interface ParsedArchflowLink {
  target: ArchflowLinkTarget
  id: string
}

/**
 * Parse a single `archflow://` URL string.
 * Returns null when the string doesn't match the scheme.
 */
export function parseArchflowLink(url: string): ParsedArchflowLink | null {
  const m = SCHEME_RE.exec(url)
  return m ? { target: m[1].toLowerCase() as ArchflowLinkTarget, id: m[2] } : null
}

// ─── Inline scan ─────────────────────────────────────────────────────────────

export interface FoundArchflowLink {
  /** Character index of the start of the raw `archflow://...` URL in `text`. */
  index: number
  /** The raw URL string as it appeared in the source text. */
  raw: string
  parsed: ParsedArchflowLink
}

// Matches bare archflow:// URIs in arbitrary text.
// The UUID portion is [a-f0-9-]{36} (lower or upper hex + hyphens).
const INLINE_RE =
  /archflow:\/\/(object|diagram|connection)\/([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})/g

/**
 * Scan `text` for every occurrence of a valid `archflow://` URL and return
 * the position, raw string, and parsed result for each one.
 *
 * Used by the markdown renderer to replace bare URIs with `<ArchflowLink>`
 * components (in addition to the standard `[label](archflow://...)` syntax
 * handled by the remark/rehype link plugin).
 */
export function findArchflowLinks(text: string): FoundArchflowLink[] {
  const results: FoundArchflowLink[] = []
  let match: RegExpExecArray | null
  INLINE_RE.lastIndex = 0
  while ((match = INLINE_RE.exec(text)) !== null) {
    const raw = match[0]
    const parsed = parseArchflowLink(raw)
    if (parsed) {
      results.push({ index: match.index, raw, parsed })
    }
  }
  return results
}
