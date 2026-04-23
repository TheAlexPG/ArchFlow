import { useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import {
  useApiKeys,
  useCreateApiKey,
  useCreateWebhook,
  useDeleteWebhook,
  useRevokeApiKey,
  useTestWebhook,
  useWebhookEventTypes,
  useWebhooks,
} from '../hooks/use-api'
import type {
  ApiKey,
  ApiKeyCreate,
  ApiKeyPermission,
  ApiKeyWithSecret,
  Webhook,
  WebhookWithSecret,
} from '../types/model'

const PERMISSIONS: { value: ApiKeyPermission; label: string; hint: string }[] = [
  { value: 'read', label: 'Read', hint: 'List/read objects, connections, diagrams' },
  { value: 'write', label: 'Write', hint: 'Create, update, delete model entities' },
  { value: 'admin', label: 'Admin', hint: 'Manage drafts, versions, members' },
]

export function SettingsPage() {
  const { data: keys = [], isLoading } = useApiKeys()
  const [createOpen, setCreateOpen] = useState(false)
  const [justCreated, setJustCreated] = useState<ApiKeyWithSecret | null>(null)

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['alex / personal', 'Settings']} />
        <div className="flex-1 overflow-y-auto p-8">
        <h1 className="text-xl font-semibold mb-6">Settings</h1>

        <section className="max-w-3xl mb-10">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold">API Keys</h2>
              <p className="text-xs text-neutral-500 mt-0.5">
                Keys let agents and scripts access your model via the REST API.
                Use the key as a Bearer token.
              </p>
            </div>
            <button
              onClick={() => setCreateOpen(true)}
              className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
            >
              + New key
            </button>
          </div>

          <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-neutral-500 border-b border-neutral-800">
                  <th className="text-left px-4 py-2 font-medium">Name</th>
                  <th className="text-left px-4 py-2 font-medium">Prefix</th>
                  <th className="text-left px-4 py-2 font-medium">Permissions</th>
                  <th className="text-left px-4 py-2 font-medium">Created</th>
                  <th className="text-left px-4 py-2 font-medium">Last used</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-4 text-xs text-neutral-500 italic"
                    >
                      Loading…
                    </td>
                  </tr>
                )}
                {!isLoading && keys.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-4 text-xs text-neutral-500 italic"
                    >
                      No API keys yet.
                    </td>
                  </tr>
                )}
                {keys.map((k) => (
                  <KeyRow key={k.id} apiKey={k} />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <WebhooksSection />
        </div>
      </div>

      {createOpen && (
        <CreateKeyModal
          onClose={() => setCreateOpen(false)}
          onCreated={(k) => {
            setCreateOpen(false)
            setJustCreated(k)
          }}
        />
      )}
      {justCreated && (
        <SecretRevealModal
          apiKey={justCreated}
          onClose={() => setJustCreated(null)}
        />
      )}
    </div>
  )
}

function WebhooksSection() {
  const { data: hooks = [], isLoading } = useWebhooks()
  const [createOpen, setCreateOpen] = useState(false)
  const [justCreated, setJustCreated] = useState<WebhookWithSecret | null>(null)

  return (
    <section className="max-w-3xl">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold">Webhooks</h2>
          <p className="text-xs text-neutral-500 mt-0.5">
            Outbound HTTP callbacks on model-change events. Every delivery is
            signed with HMAC-SHA256 in the <code>X-ArchFlow-Signature</code> header.
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
        >
          + New webhook
        </button>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-neutral-500 border-b border-neutral-800">
              <th className="text-left px-4 py-2 font-medium">URL</th>
              <th className="text-left px-4 py-2 font-medium">Events</th>
              <th className="text-left px-4 py-2 font-medium">Last delivery</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-xs text-neutral-500 italic">
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && hooks.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-xs text-neutral-500 italic">
                  No webhooks yet.
                </td>
              </tr>
            )}
            {hooks.map((h) => (
              <WebhookRow key={h.id} hook={h} />
            ))}
          </tbody>
        </table>
      </div>

      {createOpen && (
        <CreateWebhookModal
          onClose={() => setCreateOpen(false)}
          onCreated={(w) => {
            setCreateOpen(false)
            setJustCreated(w)
          }}
        />
      )}
      {justCreated && (
        <WebhookSecretModal hook={justCreated} onClose={() => setJustCreated(null)} />
      )}
    </section>
  )
}

function WebhookRow({ hook }: { hook: Webhook }) {
  const del = useDeleteWebhook()
  const test = useTestWebhook()
  const statusLabel = hook.last_status
    ? `HTTP ${hook.last_status}`
    : hook.last_delivery_at
      ? 'Unreachable'
      : 'Never fired'

  return (
    <tr className="border-b border-neutral-800 last:border-0">
      <td className="px-4 py-2 font-mono text-xs text-neutral-300 break-all">
        {hook.url}
      </td>
      <td className="px-4 py-2 text-xs text-neutral-400">{hook.events.join(', ')}</td>
      <td className="px-4 py-2 text-xs text-neutral-400">
        {hook.last_delivery_at
          ? new Date(hook.last_delivery_at).toLocaleString()
          : 'Never'}
      </td>
      <td className="px-4 py-2 text-xs">
        {!hook.enabled ? (
          <span className="text-red-400">Disabled</span>
        ) : (
          <span
            className={hook.failure_count > 0 ? 'text-amber-400' : 'text-emerald-400'}
          >
            {statusLabel}
          </span>
        )}
      </td>
      <td className="px-4 py-2 text-right whitespace-nowrap">
        <button
          onClick={() => test.mutate(hook.id)}
          disabled={test.isPending}
          className="text-xs text-neutral-300 hover:text-white mr-3 disabled:opacity-40"
        >
          {test.isPending ? 'Sending…' : 'Test'}
        </button>
        <button
          onClick={() => {
            if (confirm(`Delete webhook for ${hook.url}?`)) {
              del.mutate(hook.id)
            }
          }}
          className="text-xs text-red-400 hover:text-red-300"
        >
          Delete
        </button>
      </td>
    </tr>
  )
}

function CreateWebhookModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (w: WebhookWithSecret) => void
}) {
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>([])
  const { data: catalogue = [] } = useWebhookEventTypes()
  const create = useCreateWebhook()
  const canSubmit = url.trim().length > 0 && events.length > 0

  const submit = async () => {
    if (!canSubmit) return
    const result = await create.mutateAsync({ url: url.trim(), events })
    onCreated(result)
  }

  return (
    <ModalShell onClose={onClose} title="Create webhook">
      <label className="block text-xs text-neutral-400 mb-1">URL</label>
      <input
        autoFocus
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://example.com/hooks/archflow"
        className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm mb-4 outline-none focus:border-neutral-500"
      />

      <label className="block text-xs text-neutral-400 mb-1">
        Events ({events.length} selected)
      </label>
      <div className="max-h-48 overflow-y-auto border border-neutral-800 rounded p-2 mb-5 bg-neutral-950">
        {catalogue.map((ev) => (
          <label
            key={ev}
            className="flex items-center gap-2 text-xs cursor-pointer py-0.5"
          >
            <input
              type="checkbox"
              checked={events.includes(ev)}
              onChange={(e) =>
                setEvents(
                  e.target.checked ? [...events, ev] : events.filter((x) => x !== ev),
                )
              }
            />
            <code className="text-neutral-300">{ev}</code>
          </label>
        ))}
      </div>

      {create.isError && (
        <div className="text-xs text-red-400 mb-3">
          Could not create webhook. Check the URL and try again.
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button
          onClick={onClose}
          className="text-xs text-neutral-400 hover:text-neutral-200 px-3 py-1.5"
        >
          Cancel
        </button>
        <button
          disabled={!canSubmit || create.isPending}
          onClick={submit}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
        >
          {create.isPending ? 'Creating…' : 'Create'}
        </button>
      </div>
    </ModalShell>
  )
}

function WebhookSecretModal({
  hook,
  onClose,
}: {
  hook: WebhookWithSecret
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(hook.secret)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <ModalShell onClose={onClose} title="Webhook created">
      <div className="text-xs text-amber-400 mb-3 border border-amber-900/40 bg-amber-900/10 rounded px-3 py-2">
        Copy the signing secret now — it will not be shown again. Use it on your
        receiver to verify the <code>X-ArchFlow-Signature</code> header.
      </div>
      <div className="flex items-stretch gap-2 mb-4">
        <code className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-xs font-mono break-all">
          {hook.secret}
        </code>
        <button
          onClick={copy}
          className="bg-neutral-700 hover:bg-neutral-600 text-xs rounded px-3"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="flex justify-end">
        <button
          onClick={onClose}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
        >
          Done
        </button>
      </div>
    </ModalShell>
  )
}

function KeyRow({ apiKey }: { apiKey: ApiKey }) {
  const revoke = useRevokeApiKey()
  const revoked = apiKey.revoked_at !== null
  const expired =
    apiKey.expires_at !== null && new Date(apiKey.expires_at) < new Date()

  return (
    <tr className="border-b border-neutral-800 last:border-0">
      <td className="px-4 py-2">{apiKey.name}</td>
      <td className="px-4 py-2 font-mono text-xs text-neutral-400">
        {apiKey.key_prefix}…
      </td>
      <td className="px-4 py-2 text-xs text-neutral-400">
        {apiKey.permissions.join(', ') || '—'}
      </td>
      <td className="px-4 py-2 text-xs text-neutral-400">
        {new Date(apiKey.created_at).toLocaleDateString()}
      </td>
      <td className="px-4 py-2 text-xs text-neutral-400">
        {apiKey.last_used_at
          ? new Date(apiKey.last_used_at).toLocaleString()
          : 'Never'}
      </td>
      <td className="px-4 py-2 text-xs">
        {revoked ? (
          <span className="text-red-400">Revoked</span>
        ) : expired ? (
          <span className="text-amber-400">Expired</span>
        ) : (
          <span className="text-emerald-400">Active</span>
        )}
      </td>
      <td className="px-4 py-2 text-right">
        {!revoked && (
          <button
            onClick={() => {
              if (confirm(`Revoke "${apiKey.name}"? This can't be undone.`)) {
                revoke.mutate(apiKey.id)
              }
            }}
            className="text-xs text-red-400 hover:text-red-300"
          >
            Revoke
          </button>
        )}
      </td>
    </tr>
  )
}

function CreateKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (k: ApiKeyWithSecret) => void
}) {
  const [name, setName] = useState('')
  const [perms, setPerms] = useState<ApiKeyPermission[]>(['read'])
  const [expires, setExpires] = useState<'never' | '30' | '90' | '365'>('never')
  const create = useCreateApiKey()
  const trimmed = name.trim()

  const submit = async () => {
    if (!trimmed) return
    const payload: ApiKeyCreate = {
      name: trimmed,
      permissions: perms,
      expires_in_days: expires === 'never' ? null : parseInt(expires, 10),
    }
    const result = await create.mutateAsync(payload)
    onCreated(result)
  }

  return (
    <ModalShell onClose={onClose} title="Create API key">
      <label className="block text-xs text-neutral-400 mb-1">Name</label>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="ci-bot, terraform-sync…"
        className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm mb-4 outline-none focus:border-neutral-500"
      />

      <label className="block text-xs text-neutral-400 mb-1">Permissions</label>
      <div className="flex flex-col gap-1 mb-4">
        {PERMISSIONS.map((p) => (
          <label
            key={p.value}
            className="flex items-start gap-2 text-xs cursor-pointer"
          >
            <input
              type="checkbox"
              checked={perms.includes(p.value)}
              onChange={(e) =>
                setPerms(
                  e.target.checked
                    ? [...perms, p.value]
                    : perms.filter((x) => x !== p.value),
                )
              }
              className="mt-0.5"
            />
            <span>
              <span className="text-neutral-200">{p.label}</span>
              <span className="text-neutral-500"> — {p.hint}</span>
            </span>
          </label>
        ))}
      </div>

      <label className="block text-xs text-neutral-400 mb-1">Expires</label>
      <select
        value={expires}
        onChange={(e) => setExpires(e.target.value as typeof expires)}
        className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm mb-5 outline-none focus:border-neutral-500"
      >
        <option value="never">Never</option>
        <option value="30">In 30 days</option>
        <option value="90">In 90 days</option>
        <option value="365">In 1 year</option>
      </select>

      {create.isError && (
        <div className="text-xs text-red-400 mb-3">
          Could not create key. Try again.
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button
          onClick={onClose}
          className="text-xs text-neutral-400 hover:text-neutral-200 px-3 py-1.5"
        >
          Cancel
        </button>
        <button
          disabled={!trimmed || perms.length === 0 || create.isPending}
          onClick={submit}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
        >
          {create.isPending ? 'Creating…' : 'Create'}
        </button>
      </div>
    </ModalShell>
  )
}

function SecretRevealModal({
  apiKey,
  onClose,
}: {
  apiKey: ApiKeyWithSecret
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(apiKey.secret)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <ModalShell onClose={onClose} title={`"${apiKey.name}" created`}>
      <div className="text-xs text-amber-400 mb-3 border border-amber-900/40 bg-amber-900/10 rounded px-3 py-2">
        Copy this secret now. It will not be shown again.
      </div>
      <div className="flex items-stretch gap-2 mb-4">
        <code className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-xs font-mono break-all">
          {apiKey.secret}
        </code>
        <button
          onClick={copy}
          className="bg-neutral-700 hover:bg-neutral-600 text-xs rounded px-3"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="flex justify-end">
        <button
          onClick={onClose}
          className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5"
        >
          Done
        </button>
      </div>
    </ModalShell>
  )
}

function ModalShell({
  onClose,
  title,
  children,
}: {
  onClose: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-neutral-900 border border-neutral-800 rounded-lg w-[460px] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-4">{title}</h3>
        {children}
      </div>
    </div>
  )
}
