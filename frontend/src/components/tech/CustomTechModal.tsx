import { useEffect, useMemo, useState } from 'react'
import { Icon } from '@iconify/react'
import { Modal } from '../common/Modal'
import { Button } from '../ui'
import { cn } from '../../utils/cn'
import { useWorkspaceStore } from '../../stores/workspace-store'
import {
  useCreateCustomTechnology,
  useUpdateCustomTechnology,
} from '../../hooks/use-api'
import type {
  TechCategory,
  Technology,
  TechnologyCreate,
  TechnologyUpdate,
} from '../../types/model'
import { TechIcon } from './TechIcon'

const CATEGORIES: { value: TechCategory; label: string }[] = [
  { value: 'language', label: 'Language' },
  { value: 'framework', label: 'Framework' },
  { value: 'database', label: 'Database' },
  { value: 'cloud', label: 'Cloud' },
  { value: 'saas', label: 'SaaS' },
  { value: 'tool', label: 'Tool' },
  { value: 'protocol', label: 'Protocol' },
  { value: 'other', label: 'Other' },
]

const SUGGESTED_COLLECTIONS = ['logos', 'simple-icons', 'mdi', 'devicon']

interface IconifyHit {
  name: string
  prefix?: string
}

export interface CustomTechModalProps {
  open: boolean
  onClose: () => void
  /** Passed back after a successful create so the picker can auto-select. */
  onCreated?: (tech: Technology) => void
  /** Pre-fill fields when opening from a picker in the middle of typing. */
  initialName?: string
  initialCategory?: TechCategory
  /** If present, the modal edits an existing custom tech instead of creating. */
  existing?: Technology | null
}

/**
 * Build / edit a workspace-level custom technology. The icon browser hits the
 * public Iconify API (no auth, CORS-friendly) so users aren't limited to the
 * couple hundred built-in entries.
 */
export function CustomTechModal({
  open,
  onClose,
  onCreated,
  initialName = '',
  initialCategory,
  existing,
}: CustomTechModalProps) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const createMutation = useCreateCustomTechnology(workspaceId)
  const updateMutation = useUpdateCustomTechnology(workspaceId)
  const isEditing = Boolean(existing)

  const [name, setName] = useState(existing?.name ?? initialName)
  const [slug, setSlug] = useState(existing?.slug ?? '')
  const [category, setCategory] = useState<TechCategory>(
    existing?.category ?? initialCategory ?? 'tool',
  )
  const [color, setColor] = useState(existing?.color ?? '')
  const [aliases, setAliases] = useState((existing?.aliases ?? []).join(', '))
  const [iconifyName, setIconifyName] = useState(
    existing?.iconify_name ?? 'logos:python',
  )
  const [iconQuery, setIconQuery] = useState(initialName)
  const [iconHits, setIconHits] = useState<IconifyHit[]>([])
  const [iconLoading, setIconLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form whenever the modal is reopened so stale state from a
  // previous session doesn't leak into a fresh create.
  useEffect(() => {
    if (!open) return
    setName(existing?.name ?? initialName)
    setSlug(existing?.slug ?? '')
    setCategory(existing?.category ?? initialCategory ?? 'tool')
    setColor(existing?.color ?? '')
    setAliases((existing?.aliases ?? []).join(', '))
    setIconifyName(existing?.iconify_name ?? 'logos:python')
    setIconQuery(initialName)
    setError(null)
  }, [open, existing, initialName, initialCategory])

  // Iconify search with debounce. Free public API, no auth.
  useEffect(() => {
    if (!open) return
    const q = iconQuery.trim()
    if (!q) {
      setIconHits([])
      return
    }
    const ctrl = new AbortController()
    const t = setTimeout(async () => {
      setIconLoading(true)
      try {
        const url = new URL('https://api.iconify.design/search')
        url.searchParams.set('query', q)
        url.searchParams.set('limit', '48')
        url.searchParams.set('prefixes', SUGGESTED_COLLECTIONS.join(','))
        const res = await fetch(url, { signal: ctrl.signal })
        if (!res.ok) throw new Error(`Iconify ${res.status}`)
        const body = (await res.json()) as { icons: string[] }
        setIconHits(body.icons.map((n) => ({ name: n })))
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          // Search failure is non-fatal — user can still paste a known
          // Iconify name directly into the text field below.
          setIconHits([])
        }
      } finally {
        setIconLoading(false)
      }
    }, 220)
    return () => {
      ctrl.abort()
      clearTimeout(t)
    }
  }, [iconQuery, open])

  const canSubmit = useMemo(() => {
    return Boolean(name.trim() && iconifyName.trim() && category && workspaceId)
  }, [name, iconifyName, category, workspaceId])

  const handleSubmit = () => {
    if (!canSubmit) return
    setError(null)
    const normalizedAliases = aliases
      .split(',')
      .map((a) => a.trim().toLowerCase())
      .filter(Boolean)
    if (existing) {
      const payload: TechnologyUpdate = {
        name: name.trim(),
        iconify_name: iconifyName.trim(),
        category,
        color: color.trim() || null,
        aliases: normalizedAliases.length ? normalizedAliases : null,
      }
      updateMutation.mutate(
        { id: existing.id, update: payload },
        {
          onSuccess: (tech) => {
            onCreated?.(tech)
            onClose()
          },
          onError: (e: unknown) => setError(toMessage(e)),
        },
      )
    } else {
      const payload: TechnologyCreate = {
        name: name.trim(),
        slug: slug.trim() || undefined,
        iconify_name: iconifyName.trim(),
        category,
        color: color.trim() || null,
        aliases: normalizedAliases.length ? normalizedAliases : null,
      }
      createMutation.mutate(payload, {
        onSuccess: (tech) => {
          onCreated?.(tech)
          onClose()
        },
        onError: (e: unknown) => setError(toMessage(e)),
      })
    }
  }

  const submitting = createMutation.isPending || updateMutation.isPending

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEditing ? 'Edit custom technology' : 'New custom technology'}
      width={560}
      footer={
        <>
          {error && (
            <span className="text-[11.5px] text-accent-pink mr-auto font-mono">
              {error}
            </span>
          )}
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
          >
            {submitting ? 'Saving…' : isEditing ? 'Save changes' : 'Create technology'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <TechIcon iconifyName={iconifyName} size={32} />
          <div className="flex-1">
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
              Name
            </label>
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (!iconQuery) setIconQuery(e.target.value)
              }}
              placeholder="e.g. AcmeCorp Billing"
              className="w-full bg-surface border border-border-base rounded px-2 py-1.5 text-[12.5px] text-text-base outline-none focus:border-coral"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
              Slug {isEditing ? '(locked)' : '(optional)'}
            </label>
            <input
              value={slug}
              disabled={isEditing}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="auto from name"
              className="w-full bg-surface border border-border-base rounded px-2 py-1.5 font-mono text-[11.5px] text-text-base outline-none focus:border-coral disabled:opacity-50"
            />
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as TechCategory)}
              className="w-full bg-surface border border-border-base rounded px-2 py-1.5 text-[12.5px] text-text-base outline-none focus:border-coral"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
              Color (hex)
            </label>
            <div className="relative">
              <input
                value={color}
                onChange={(e) => setColor(e.target.value)}
                placeholder="#336791"
                className="w-full bg-surface border border-border-base rounded pl-7 pr-2 py-1.5 font-mono text-[11.5px] text-text-base outline-none focus:border-coral"
              />
              <span
                className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 rounded border border-border-base"
                style={{ background: color || 'transparent' }}
              />
            </div>
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3 mb-1">
              Aliases (comma-separated)
            </label>
            <input
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              placeholder="pg, postgres"
              className="w-full bg-surface border border-border-base rounded px-2 py-1.5 font-mono text-[11.5px] text-text-base outline-none focus:border-coral"
            />
          </div>
        </div>

        <div>
          <div className="flex items-end justify-between gap-2 mb-1">
            <label className="block font-mono text-[10px] uppercase tracking-[0.08em] text-text-3">
              Iconify icon
            </label>
            <input
              value={iconifyName}
              onChange={(e) => setIconifyName(e.target.value)}
              placeholder="logos:python"
              className="flex-1 max-w-[220px] bg-surface border border-border-base rounded px-2 py-1 font-mono text-[11px] text-text-base outline-none focus:border-coral"
            />
          </div>
          <div className="bg-surface border border-border-base rounded p-2">
            <input
              value={iconQuery}
              onChange={(e) => setIconQuery(e.target.value)}
              placeholder="Search icons (e.g. database, figma, kubernetes)…"
              className="w-full bg-transparent font-mono text-[11px] text-text-base placeholder:text-text-4 outline-none mb-2"
            />
            <div className="grid grid-cols-8 gap-1 max-h-[180px] overflow-y-auto">
              {iconLoading && (
                <div className="col-span-8 py-4 text-center font-mono text-[10.5px] text-text-3">
                  Searching…
                </div>
              )}
              {!iconLoading && iconHits.length === 0 && iconQuery.trim() && (
                <div className="col-span-8 py-4 text-center font-mono text-[10.5px] text-text-3">
                  No matches on iconify.design
                </div>
              )}
              {iconHits.map((hit) => (
                <button
                  type="button"
                  key={hit.name}
                  onClick={() => setIconifyName(hit.name)}
                  className={cn(
                    'flex items-center justify-center aspect-square rounded',
                    'border transition-colors',
                    iconifyName === hit.name
                      ? 'border-coral bg-coral-glow'
                      : 'border-transparent hover:border-border-hi hover:bg-surface-hi',
                  )}
                  title={hit.name}
                >
                  <Icon icon={hit.name} width={18} height={18} />
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function toMessage(e: unknown): string {
  if (!e) return 'Unknown error'
  // Axios error shape: e.response.data.detail is the common server payload.
  const err = e as {
    response?: { data?: { detail?: string | { detail?: string } } }
    message?: string
  }
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'detail' in detail && typeof detail.detail === 'string') {
    return detail.detail
  }
  return err.message ?? 'Could not save custom technology'
}
