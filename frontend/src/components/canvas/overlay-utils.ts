import type { ModelObject } from '../../types/model'
import { STATUS_COLORS } from './node-utils'

export type FilterDim = 'none' | 'tags' | 'technology' | 'status' | 'teams'

/**
 * Deterministic HSL color from an arbitrary string — used to tint nodes by
 * tag/technology/team when the corresponding filter is active. Hue-only so
 * colors stay visually consistent against the dark canvas.
 */
export function stringToColor(s: string): string {
  let hash = 0
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) | 0
  }
  const hue = ((hash % 360) + 360) % 360
  return `hsl(${hue} 65% 55%)`
}

/** The primary "value" of an object for a given filter dimension. */
export function extractFilterValue(obj: ModelObject, dim: FilterDim): string | null {
  if (dim === 'none') return null
  if (dim === 'status') return obj.status
  if (dim === 'teams') return obj.owner_team || null
  if (dim === 'tags') return obj.tags?.[0] || null
  if (dim === 'technology') return obj.technology?.[0] || null
  return null
}

/** Color assigned to a value for the given dimension. */
export function colorForValue(value: string, dim: FilterDim): string {
  if (dim === 'status') {
    return STATUS_COLORS[value as keyof typeof STATUS_COLORS] || '#737373'
  }
  return stringToColor(value)
}

/**
 * Returns an overlay style for a node when a filter dimension is active:
 * - a colored ring around the node (via outline) for its value
 * - null when no dim active or the object has no value for that dim.
 */
export function overlayStyleFor(
  obj: ModelObject,
  dim: FilterDim,
): { outline: string; outlineOffset: string } | null {
  const value = extractFilterValue(obj, dim)
  if (!value) return null
  const color = colorForValue(value, dim)
  return { outline: `2px solid ${color}`, outlineOffset: '2px' }
}

/**
 * Collects all distinct values for a given dimension across a set of objects,
 * paired with the number of objects that have that value. Used to render a
 * legend strip at the bottom of the canvas.
 */
export function collectLegend(
  objects: ModelObject[],
  dim: FilterDim,
): { value: string; color: string; count: number }[] {
  if (dim === 'none') return []
  const counts = new Map<string, number>()
  for (const obj of objects) {
    const values: string[] = []
    if (dim === 'tags') values.push(...(obj.tags || []))
    else if (dim === 'technology') values.push(...(obj.technology || []))
    else {
      const v = extractFilterValue(obj, dim)
      if (v) values.push(v)
    }
    for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, color: colorForValue(value, dim), count }))
    .sort((a, b) => b.count - a.count)
}
