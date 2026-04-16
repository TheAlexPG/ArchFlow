import type { ObjectStatus, ObjectType } from '../../types/model'

export const TYPE_ICONS: Record<ObjectType, string> = {
  system: '■',
  actor: '👤',
  external_system: '☁',
  group: '▢',
  app: '⊞',
  store: '⊟',
  component: '◧',
}

export const TYPE_LABELS: Record<ObjectType, string> = {
  system: 'System',
  actor: 'Actor',
  external_system: 'External System',
  group: 'Group',
  app: 'App',
  store: 'Store',
  component: 'Component',
}

export const STATUS_COLORS: Record<ObjectStatus, string> = {
  live: '#22c55e',
  future: '#a855f7',
  deprecated: '#f97316',
  removed: '#ef4444',
}

export const STATUS_BG: Record<ObjectStatus, string> = {
  live: 'rgba(34, 197, 94, 0.15)',
  future: 'rgba(168, 85, 247, 0.15)',
  deprecated: 'rgba(249, 115, 22, 0.15)',
  removed: 'rgba(239, 68, 68, 0.15)',
}

export const TYPE_BORDER_COLORS: Record<ObjectType, string> = {
  system: '#3b82f6',
  actor: '#8b5cf6',
  external_system: '#6b7280',
  group: '#6b7280',
  app: '#06b6d4',
  store: '#f59e0b',
  component: '#10b981',
}

/**
 * Strip HTML tags and decode basic entities for preview display on nodes.
 * Descriptions are stored as TipTap HTML; on the canvas we only want plain text.
 */
export function stripHtml(html: string | null | undefined): string {
  if (!html) return ''
  const text = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
  const el = document.createElement('textarea')
  el.innerHTML = text
  return el.value
}
