import { useMemo, useState } from 'react'
import { AppSidebar } from '../components/nav/AppSidebar'
import { PageToolbar } from '../components/nav/PageToolbar'
import { AnalyticsConsentModal } from '../components/agents-settings/AnalyticsConsentModal'
import { PerAgentOverrideTable } from '../components/agents-settings/PerAgentOverrideTable'
import { ModelPricingTable } from '../components/agents-settings/ModelPricingTable'
import {
  useAgentsSettings,
  useUpdateAgentsSettings,
  type AgentSettings,
  type AgentSettingsUpdate,
  type AnalyticsConsent,
  type AgentEditsPolicy,
  type ModelPricing,
  type PerAgentSettings,
} from '../hooks/use-agents-settings'
import { useWorkspaceStore } from '../stores/workspace-store'
import { useWorkspaces } from '../hooks/use-api'

// ─── Provider catalog ───────────────────────────────────────────────────────

type ProviderId = 'openai' | 'anthropic' | 'openrouter' | 'custom'

const PROVIDER_OPTIONS: { value: ProviderId; label: string }[] = [
  { value: 'openai', label: 'openai' },
  { value: 'anthropic', label: 'anthropic' },
  { value: 'openrouter', label: 'openrouter' },
  { value: 'custom', label: 'Custom (OpenAI-compatible)' },
]

const PROVIDER_BASE_URL: Record<Exclude<ProviderId, 'custom'>, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  openrouter: 'https://openrouter.ai/api/v1',
}

const MODEL_CATALOG: Record<Exclude<ProviderId, 'custom'>, string[]> = {
  openai: [
    'openai/gpt-4o',
    'openai/gpt-4o-mini',
    'openai/gpt-4.1',
    'openai/gpt-4.1-mini',
    'openai/o1',
    'openai/o1-mini',
    'openai/o3-mini',
  ],
  anthropic: [
    'anthropic/claude-opus-4-5',
    'anthropic/claude-sonnet-4-5',
    'anthropic/claude-haiku-4-5',
    'anthropic/claude-opus-4',
    'anthropic/claude-sonnet-4',
  ],
  openrouter: [
    'openrouter/anthropic/claude-sonnet-4.5',
    'openrouter/openai/gpt-4o',
    'openrouter/google/gemini-2.5-pro',
    'openrouter/meta-llama/llama-3.3-70b-instruct',
    'openrouter/qwen/qwen-2.5-72b-instruct',
    'openrouter/deepseek/deepseek-r1',
  ],
}

function normalizeProvider(raw: string | null | undefined): ProviderId {
  if (raw === 'openai' || raw === 'anthropic' || raw === 'openrouter') return raw
  // Empty / unknown / explicit "custom" all collapse to custom — the user
  // can still pick a known provider afterwards.
  return 'custom'
}

// ─── Draft state shape ──────────────────────────────────────────────────────

/**
 * Draft is a deep partial mirror of AgentSettings. We keep it null until
 * the GET resolves, then seed it once. All edits flow into this object;
 * Save computes a diff vs the original snapshot and PUTs only what changed
 * — null clears, missing keys leave the value alone (per backend deep-merge).
 */
interface DraftState {
  litellm: {
    provider: ProviderId
    base_url: string
    model_default: string
    /** Manual context-window override. Empty string = no override (auto-detect). */
    context_window: string
    /** Plaintext API key the user just typed; null means "not touched". */
    api_key: string | null
    /** True only when the user explicitly clicked "Clear". */
    api_key_cleared: boolean
  }
  analytics_consent: AnalyticsConsent
  agent_edits_policy: AgentEditsPolicy
  agents: Record<string, PerAgentSettings>
  model_pricing: Record<string, ModelPricing>
}

function seedDraft(s: AgentSettings): DraftState {
  const provider = normalizeProvider(s.litellm.provider)
  // Auto-derive base_url for known providers if the server didn't store one
  // — keeps the "save sends a sane value" guarantee for first-time setups.
  const baseUrl =
    provider === 'custom'
      ? (s.litellm.base_url ?? '')
      : (s.litellm.base_url ?? PROVIDER_BASE_URL[provider])
  return {
    litellm: {
      provider,
      base_url: baseUrl,
      model_default: s.litellm.model_default ?? '',
      context_window:
        s.litellm.context_window !== null && s.litellm.context_window !== undefined
          ? String(s.litellm.context_window)
          : '',
      api_key: null,
      api_key_cleared: false,
    },
    analytics_consent: s.analytics_consent,
    agent_edits_policy: s.agent_edits_policy,
    agents: { ...s.agents },
    model_pricing: { ...s.model_pricing },
  }
}

// ─── Diff helper ────────────────────────────────────────────────────────────

/**
 * Compare draft to original and produce the smallest possible PUT body —
 * only fields that actually changed. The endpoint deep-merges, so we
 * leave unchanged keys out entirely. `null` is reserved for clearing.
 */
function computeDiff(
  draft: DraftState,
  original: AgentSettings,
): AgentSettingsUpdate {
  const out: AgentSettingsUpdate = {}

  // ── LLM ──────────────────────────────────────────────────────────────
  const llm: AgentSettingsUpdate['litellm'] = {}
  const origProvider = normalizeProvider(original.litellm.provider)
  if (draft.litellm.provider !== origProvider) {
    llm.provider = draft.litellm.provider
  }
  if (draft.litellm.base_url !== (original.litellm.base_url ?? '')) {
    llm.base_url = draft.litellm.base_url
  }
  if (draft.litellm.model_default !== (original.litellm.model_default ?? '')) {
    llm.model_default = draft.litellm.model_default
  }
  // context_window: empty input ⇒ null (clear override); non-empty parsed to number.
  const draftCw = draft.litellm.context_window.trim()
  const draftCwParsed: number | null = draftCw === '' ? null : Number(draftCw)
  const origCw = original.litellm.context_window ?? null
  if (
    draftCwParsed !== origCw &&
    !(draftCwParsed !== null && Number.isNaN(draftCwParsed))
  ) {
    llm.context_window = draftCwParsed
  }
  if (draft.litellm.api_key !== null) {
    llm.api_key = draft.litellm.api_key
  } else if (draft.litellm.api_key_cleared && original.litellm.has_key) {
    llm.api_key = null
  }
  if (Object.keys(llm).length) out.litellm = llm

  // ── Top-level scalars ────────────────────────────────────────────────
  if (draft.analytics_consent !== original.analytics_consent) {
    out.analytics_consent = draft.analytics_consent
  }
  if (draft.agent_edits_policy !== original.agent_edits_policy) {
    out.agent_edits_policy = draft.agent_edits_policy
  }

  // ── Per-agent overrides ──────────────────────────────────────────────
  // Send each agent's full override block whenever any of its values
  // differ from the original. The backend stores per-key, so this works.
  const agentDiff: Record<string, PerAgentSettings> = {}
  for (const [aid, ov] of Object.entries(draft.agents)) {
    const orig = original.agents[aid] ?? {}
    const fields: (keyof PerAgentSettings)[] = [
      'model',
      'turn_limit',
      'budget_usd',
      'budget_scope',
      'context_threshold',
    ]
    if (fields.some((f) => (ov[f] ?? null) !== (orig[f] ?? null))) {
      agentDiff[aid] = ov
    }
  }
  if (Object.keys(agentDiff).length) out.agents = agentDiff

  // ── Model pricing ────────────────────────────────────────────────────
  const priceDiff: Record<string, ModelPricing> = {}
  for (const [mid, p] of Object.entries(draft.model_pricing)) {
    const orig = original.model_pricing[mid]
    if (
      !orig ||
      orig.input_per_million !== p.input_per_million ||
      orig.output_per_million !== p.output_per_million
    ) {
      priceDiff[mid] = p
    }
  }
  if (Object.keys(priceDiff).length) out.model_pricing = priceDiff

  return out
}

// ─── Page ───────────────────────────────────────────────────────────────────

export function AgentsSettingsPage() {
  const wsId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const { data: workspaces = [] } = useWorkspaces()
  const currentWs = workspaces.find((w) => w.id === wsId) ?? null
  const isAdmin = currentWs?.role === 'owner' || currentWs?.role === 'admin'

  const settings = useAgentsSettings({ enabled: isAdmin })
  const update = useUpdateAgentsSettings()

  const [draft, setDraft] = useState<DraftState | null>(null)
  const [consentModalOpen, setConsentModalOpen] = useState(false)
  /** Captures the previous (off) value so Cancel can roll back. */
  const [pendingConsent, setPendingConsent] = useState<AnalyticsConsent>('full')

  // Seed draft once when the GET first resolves. Doing this in render
  // (instead of useEffect) avoids the cascading-render lint and matches
  // the React docs' recommendation for "derived state initialised from
  // a prop/external value". The `if (draft === null)` guard means we
  // only seed once — afterwards the user owns the draft.
  if (draft === null && settings.data) {
    setDraft(seedDraft(settings.data))
  }

  const dirty = useMemo(() => {
    if (!draft || !settings.data) return false
    const diff = computeDiff(draft, settings.data)
    return Object.keys(diff).length > 0
  }, [draft, settings.data])

  // ── Permission gate ──────────────────────────────────────────────────
  if (!isAdmin) {
    return (
      <div className="flex h-screen bg-bg text-text-base">
        <AppSidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <PageToolbar breadcrumb={['Workspace', 'Agent settings']} />
          <div className="flex-1 flex items-center justify-center p-8">
            <div
              data-testid="permission-gate"
              className="text-sm text-text-2 max-w-md text-center"
            >
              You need admin permissions to view agent settings.
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Loading / error ──────────────────────────────────────────────────
  if (settings.isLoading || !draft || !settings.data) {
    return (
      <div className="flex h-screen bg-bg text-text-base">
        <AppSidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <PageToolbar breadcrumb={['Workspace', 'Agent settings']} />
          <div
            data-testid="agents-settings-loading"
            className="flex-1 flex items-center justify-center text-sm text-text-3"
          >
            Loading…
          </div>
        </div>
      </div>
    )
  }

  if (settings.error) {
    return (
      <div className="flex h-screen bg-bg text-text-base">
        <AppSidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <PageToolbar breadcrumb={['Workspace', 'Agent settings']} />
          <div className="flex-1 flex items-center justify-center text-sm text-red-400">
            Could not load settings.
          </div>
        </div>
      </div>
    )
  }

  const original = settings.data

  // ── Handlers ─────────────────────────────────────────────────────────

  const setLLM = (patch: Partial<DraftState['litellm']>) => {
    setDraft((d) => (d ? { ...d, litellm: { ...d.litellm, ...patch } } : d))
  }

  const onProviderChange = (next: ProviderId) => {
    setDraft((d) => {
      if (!d) return d
      // Auto-derive base_url for known providers; clear it when switching
      // to "custom" so the user is forced to fill it in.
      const nextBase =
        next === 'custom' ? '' : PROVIDER_BASE_URL[next]
      return {
        ...d,
        litellm: { ...d.litellm, provider: next, base_url: nextBase },
      }
    })
  }

  const onConsentChange = (next: AnalyticsConsent) => {
    if (!draft) return
    // Switching FROM 'off' TO any opt-in level requires the modal.
    // Switching to 'off' just commits — opting out is always a free action.
    const optingIn =
      draft.analytics_consent === 'off' &&
      (next === 'full' || next === 'errors_only')
    if (optingIn) {
      setPendingConsent(next)
      setConsentModalOpen(true)
      return
    }
    setDraft({ ...draft, analytics_consent: next })
  }

  const confirmConsent = (chosen: AnalyticsConsent) => {
    setConsentModalOpen(false)
    if (draft) setDraft({ ...draft, analytics_consent: chosen })
  }

  const onAgentChange = (
    agentId: string,
    field: keyof PerAgentSettings,
    value: string | number | null,
  ) => {
    setDraft((d) => {
      if (!d) return d
      const prev = d.agents[agentId] ?? {}
      const nextOverrides = { ...prev, [field]: value }
      return { ...d, agents: { ...d.agents, [agentId]: nextOverrides } }
    })
  }

  const onPricingChange = (modelId: string, value: ModelPricing | null) => {
    setDraft((d) => {
      if (!d) return d
      const next = { ...d.model_pricing }
      if (value === null) {
        delete next[modelId]
      } else {
        next[modelId] = value
      }
      return { ...d, model_pricing: next }
    })
  }

  const onSave = async () => {
    if (!draft || !original) return
    const diff = computeDiff(draft, original)
    if (Object.keys(diff).length === 0) return
    await update.mutateAsync(diff)
    // Re-seed from server's merged response (set into the cache by the
    // mutation's onSuccess) — clearing api_key plaintext + dirty flag.
    setDraft((d) =>
      d
        ? {
            ...d,
            litellm: { ...d.litellm, api_key: null, api_key_cleared: false },
          }
        : d,
    )
  }

  const onDiscard = () => {
    setDraft(seedDraft(original))
  }

  // ── Derived view-data ────────────────────────────────────────────────

  const isCustomProvider = draft.litellm.provider === 'custom'
  const modelDatalistId = 'agent-model-options'
  const modelOptions: string[] = isCustomProvider
    ? []
    : MODEL_CATALOG[draft.litellm.provider as Exclude<ProviderId, 'custom'>]

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen bg-bg text-text-base">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageToolbar breadcrumb={['Workspace', 'Agent settings']} />
        <div className="flex-1 overflow-y-auto p-8 pb-32">
          <h1 className="text-xl font-semibold mb-1">Agent settings</h1>
          <p className="text-xs text-text-3 mb-8 max-w-2xl">
            Configure your workspace&apos;s AI agents — pick an LLM provider,
            plug in your API key, set privacy preferences, and tune per-agent
            overrides. Changes apply to all members of this workspace.
          </p>

          {/* ── 1. LLM Provider ──────────────────────────────────────── */}
          <Section
            title="LLM Provider"
            hint="Bring your own model. Pick a known provider or point at any OpenAI-compatible endpoint."
          >
            <Field label="Provider">
              <select
                data-testid="llm-provider"
                value={draft.litellm.provider}
                onChange={(e) =>
                  onProviderChange(e.target.value as ProviderId)
                }
                className={inputCls}
              >
                {PROVIDER_OPTIONS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>

            {isCustomProvider ? (
              <Field label="Base URL">
                <input
                  data-testid="llm-base-url"
                  value={draft.litellm.base_url}
                  onChange={(e) => setLLM({ base_url: e.target.value })}
                  placeholder="https://my-proxy.example.com/v1"
                  className={inputCls}
                />
                <p className="text-[11px] text-text-3 mt-1">
                  Must speak the OpenAI Chat Completions protocol.
                </p>
              </Field>
            ) : (
              <Field label="Base URL">
                <input
                  data-testid="llm-base-url"
                  value={draft.litellm.base_url}
                  readOnly
                  className={`${inputCls} text-text-3 cursor-not-allowed`}
                />
              </Field>
            )}

            <Field label="Default model">
              {isCustomProvider ? (
                <input
                  data-testid="llm-model-default"
                  value={draft.litellm.model_default}
                  onChange={(e) =>
                    setLLM({ model_default: e.target.value })
                  }
                  placeholder="my-org/my-model"
                  className={inputCls}
                />
              ) : (
                <>
                  {/* datalist-backed input gives us a typeahead with the
                      catalog while still letting users paste a custom name. */}
                  <input
                    data-testid="llm-model-default"
                    list={modelDatalistId}
                    value={draft.litellm.model_default}
                    onChange={(e) =>
                      setLLM({ model_default: e.target.value })
                    }
                    placeholder="Pick from list or type a custom name"
                    className={inputCls}
                  />
                  <datalist id={modelDatalistId}>
                    {modelOptions.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <p className="text-[11px] text-text-3 mt-1">
                    Suggestions for {draft.litellm.provider}; you can also type
                    a fully-custom model name.
                  </p>
                </>
              )}
            </Field>

            <Field label="Context window override (tokens)">
              <input
                data-testid="llm-context-window"
                type="number"
                min={1}
                value={draft.litellm.context_window}
                onChange={(e) =>
                  setLLM({ context_window: e.target.value })
                }
                placeholder="auto-detect"
                className={inputCls}
              />
              <p className="text-[11px] text-text-3 mt-1">
                Leave blank to let LiteLLM auto-detect. Set a value (e.g.{' '}
                <code className="font-mono">32768</code>) when running a local
                model LiteLLM doesn&apos;t recognise.
              </p>
            </Field>

            <Field label="API key">
              <div className="flex items-center gap-2">
                <input
                  data-testid="llm-api-key"
                  type="password"
                  value={draft.litellm.api_key ?? ''}
                  onChange={(e) =>
                    setLLM({
                      api_key: e.target.value === '' ? null : e.target.value,
                      api_key_cleared: false,
                    })
                  }
                  placeholder={
                    original.litellm.has_key && draft.litellm.api_key === null
                      ? '••••••••••• (saved)'
                      : 'sk-…'
                  }
                  className={inputCls}
                />
                {original.litellm.has_key &&
                  draft.litellm.api_key === null &&
                  !draft.litellm.api_key_cleared && (
                    <span
                      data-testid="llm-api-key-saved"
                      className="text-[10px] uppercase tracking-wider text-emerald-400 border border-emerald-900/40 bg-emerald-900/10 rounded px-2 py-0.5"
                    >
                      Saved
                    </span>
                  )}
                {original.litellm.has_key &&
                  draft.litellm.api_key === null &&
                  !draft.litellm.api_key_cleared && (
                    <button
                      type="button"
                      onClick={() =>
                        setLLM({ api_key: null, api_key_cleared: true })
                      }
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Clear
                    </button>
                  )}
                {draft.litellm.api_key_cleared && (
                  <span className="text-[10px] uppercase tracking-wider text-amber-400">
                    Will clear on save
                  </span>
                )}
              </div>
              <p className="text-[11px] text-text-3 mt-1">
                {original.litellm.has_key
                  ? 'A key is already saved. Type a new value to replace it.'
                  : 'No key saved yet — agents will fall back to the bundled key (if any).'}
              </p>
            </Field>
          </Section>

          {/* ── 2. Privacy / Analytics ──────────────────────────────── */}
          <Section
            title="Privacy / Analytics"
            hint="Controls whether agent traces are sent to the self-hosted Langfuse instance."
          >
            <p className="text-[11px] text-text-3 mb-2">
              Current mode:{' '}
              <span
                data-testid="analytics-current-mode"
                className="font-mono text-text-2"
              >
                {original.analytics_consent}
              </span>
            </p>
            <div className="flex flex-col gap-2">
              {ANALYTICS_OPTIONS.map((opt) => (
                <CardRadio
                  key={opt.value}
                  name="analytics_consent"
                  value={opt.value}
                  checked={draft.analytics_consent === opt.value}
                  onSelect={() => onConsentChange(opt.value)}
                  label={opt.label}
                  hint={opt.hint}
                  testId={`analytics-${opt.value}`}
                />
              ))}
            </div>
          </Section>

          {/* ── 3. Drafts policy ─────────────────────────────────────── */}
          <Section
            title="Agent edits policy"
            hint="How agents apply structural changes — directly to the live model, only via drafts, or by asking each time."
          >
            <div className="flex flex-col gap-2">
              {EDITS_POLICY_OPTIONS.map((opt) => (
                <CardRadio
                  key={opt.value}
                  name="agent_edits_policy"
                  value={opt.value}
                  checked={draft.agent_edits_policy === opt.value}
                  onSelect={() =>
                    setDraft({ ...draft, agent_edits_policy: opt.value })
                  }
                  label={opt.label}
                  hint={opt.hint}
                  testId={`policy-${opt.value}`}
                />
              ))}
            </div>
          </Section>

          {/* ── 4. Per-agent overrides ──────────────────────────────── */}
          <Section
            title="Per-agent overrides"
            hint="Optional overrides for the bundled agents. Leave blank to inherit defaults."
          >
            <PerAgentOverrideTable
              agents={draft.agents}
              defaultModel={draft.litellm.model_default || null}
              onChange={onAgentChange}
            />
          </Section>

          {/* ── 5. Model pricing override ───────────────────────────── */}
          <Section
            title="Model pricing override"
            hint="Override LiteLLM's default $/1M-token pricing for cost computation. Use only if your provider's prices differ."
          >
            <ModelPricingTable
              pricing={draft.model_pricing}
              onChange={onPricingChange}
            />
          </Section>
        </div>

        {/* ── Sticky save bar ──────────────────────────────────────── */}
        <div className="border-t border-border-base bg-panel px-8 py-3 flex items-center justify-end gap-2">
          {update.isError && (
            <span className="text-xs text-red-400 mr-auto">
              Could not save — try again.
            </span>
          )}
          <button
            type="button"
            onClick={onDiscard}
            disabled={!dirty || update.isPending}
            data-testid="discard-btn"
            className="text-xs text-text-2 hover:text-text-base px-3 py-1.5 disabled:opacity-40"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!dirty || update.isPending}
            data-testid="save-btn"
            className="bg-coral hover:bg-coral-2 text-on-accent text-xs font-medium rounded px-4 py-1.5 disabled:bg-surface-hi disabled:text-text-3 disabled:border disabled:border-border-base disabled:opacity-100 disabled:cursor-not-allowed"
          >
            {update.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      <AnalyticsConsentModal
        open={consentModalOpen}
        initialValue={pendingConsent === 'off' ? 'full' : pendingConsent}
        onConfirm={confirmConsent}
        onCancel={() => setConsentModalOpen(false)}
      />
    </div>
  )
}

// ─── Option catalogs (used by card radios) ──────────────────────────────────

const ANALYTICS_OPTIONS: {
  value: AnalyticsConsent
  label: string
  hint: string
}[] = [
  { value: 'full', label: 'full', hint: 'Send all traces to Langfuse (recommended)' },
  { value: 'errors_only', label: 'errors_only', hint: 'Only send error traces' },
  { value: 'off', label: 'off', hint: 'No telemetry' },
]

const EDITS_POLICY_OPTIONS: {
  value: AgentEditsPolicy
  label: string
  hint: string
}[] = [
  {
    value: 'live',
    label: 'Live',
    hint: 'Apply edits directly to the live diagram (default).',
  },
  {
    value: 'drafts',
    label: 'Drafts',
    hint: 'Always edit inside a draft; never touch live.',
  },
  {
    value: 'ask',
    label: 'Ask',
    hint: 'Ask before each edit session whether to use a draft or live.',
  },
]

// ─── Layout primitives ──────────────────────────────────────────────────────

const inputCls =
  'w-full bg-surface border border-border-base rounded px-2 py-1.5 text-sm text-text-base placeholder:text-text-4 outline-none focus:border-border-hi'

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="max-w-3xl mb-10">
      <h2 className="text-sm font-semibold mb-1">{title}</h2>
      {hint && <p className="text-xs text-text-3 mb-3">{hint}</p>}
      <div className="space-y-3">{children}</div>
    </section>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs text-text-2 mb-1">{label}</label>
      {children}
    </div>
  )
}

function CardRadio({
  name,
  value,
  checked,
  onSelect,
  label,
  hint,
  testId,
}: {
  name: string
  value: string
  checked: boolean
  onSelect: () => void
  label: string
  hint: string
  testId: string
}) {
  return (
    <label
      className={`flex items-start gap-3 cursor-pointer rounded-md border px-3 py-2 transition-colors ${
        checked
          ? 'border-coral/60 bg-coral-glow'
          : 'border-border-base bg-surface/60 hover:border-border-hi'
      }`}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={onSelect}
        data-testid={testId}
        className="mt-0.5"
      />
      <span className="flex flex-col">
        <span className="text-xs font-medium text-text-base">{label}</span>
        <span className="text-[11px] text-text-2 mt-0.5">{hint}</span>
      </span>
    </label>
  )
}
