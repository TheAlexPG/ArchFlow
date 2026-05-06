import { useEffect, useRef, useState } from 'react'
import {
  useGitHubTokenStatus,
  useLookupRepo,
  type RepoLookupResult,
} from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { SectionLabel } from '../ui'

// Repo links live only on Container (app/store) and System nodes.
const REPO_ELIGIBLE_TYPES = new Set(['system', 'app', 'store'])

/** Minimal subset of ModelObject the field needs — keeps testability tight. */
interface RepoFieldObject {
  id: string
  type: string
  repo_url: string | null
  repo_branch: string | null
}

interface GitHubRepoFieldProps {
  obj: RepoFieldObject
  onChange: (
    patch: { repo_url?: string | null; repo_branch?: string | null },
  ) => void
}

interface ApiError {
  response?: {
    status?: number
    data?: { detail?: { error?: string; message?: string } | string }
  }
}

function describeError(err: unknown): string {
  const e = err as ApiError | undefined
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    return detail.message ?? detail.error ?? 'Lookup failed.'
  }
  return 'Lookup failed.'
}

function errorKind(err: unknown): 'not_found' | 'unauthorized' | 'invalid' | 'other' {
  const e = err as ApiError | undefined
  const status = e?.response?.status
  const detail = e?.response?.data?.detail
  const code =
    typeof detail === 'object' && detail !== null
      ? detail.error ?? null
      : null
  if (status === 404 || code === 'not_found') return 'not_found'
  if (code === 'unauthorized') return 'unauthorized'
  if (code === 'invalid_repo_url') return 'invalid'
  return 'other'
}

export function GitHubRepoField({ obj, onChange }: GitHubRepoFieldProps) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const tokenStatus = useGitHubTokenStatus(workspaceId)
  const lookup = useLookupRepo()

  const eligible = REPO_ELIGIBLE_TYPES.has(obj.type)

  // Local state so the user can type freely without firing a request per
  // keystroke; we only validate-on-blur.
  const [urlDraft, setUrlDraft] = useState(obj.repo_url ?? '')
  const [branchDraft, setBranchDraft] = useState(obj.repo_branch ?? '')
  const [showAdvanced, setShowAdvanced] = useState(
    () => !!(obj.repo_branch && obj.repo_branch.length > 0),
  )
  const [validationOk, setValidationOk] = useState<RepoLookupResult | null>(null)
  const [validationErr, setValidationErr] = useState<string | null>(null)
  const lastObjId = useRef(obj.id)

  // Reset drafts whenever the inspector switches to a different object.
  useEffect(() => {
    if (obj.id !== lastObjId.current) {
      setUrlDraft(obj.repo_url ?? '')
      setBranchDraft(obj.repo_branch ?? '')
      setShowAdvanced(!!(obj.repo_branch && obj.repo_branch.length > 0))
      setValidationOk(null)
      setValidationErr(null)
      lastObjId.current = obj.id
    }
  }, [obj.id, obj.repo_url, obj.repo_branch])

  // The status query 403/404s for non-owners — we still want the field
  // usable, just without the enforced "linked" indicator. So treat any
  // resolved-or-errored fetch as "stop disabling".
  const tokenLoading = tokenStatus.isLoading
  const tokenLinked = tokenStatus.data?.linked === true
  const noTokenAccess = tokenStatus.isError
  const inputDisabled = !eligible || tokenLoading || (!tokenLinked && !noTokenAccess)

  if (!eligible) {
    return null
  }

  const performLookup = async (raw: string) => {
    const trimmed = raw.trim()
    setValidationOk(null)
    setValidationErr(null)
    if (!trimmed) return null
    try {
      const result = await lookup.mutateAsync(trimmed)
      setValidationOk(result)
      return result
    } catch (err) {
      const kind = errorKind(err)
      const msg =
        kind === 'not_found'
          ? 'Repository not found or not visible to your token.'
          : kind === 'unauthorized'
            ? 'GitHub rejected the workspace token.'
            : kind === 'invalid'
              ? 'Not a recognised GitHub URL.'
              : describeError(err)
      setValidationErr(msg)
      return null
    }
  }

  const handleUrlBlur = async () => {
    const trimmed = urlDraft.trim()
    const previous = obj.repo_url ?? ''
    if (trimmed === previous) {
      // Nothing changed; clear any stale local validation messages.
      setValidationOk(null)
      setValidationErr(null)
      return
    }
    if (!trimmed) {
      // User cleared the field — drop the link entirely.
      onChange({ repo_url: null, repo_branch: null })
      setBranchDraft('')
      return
    }
    const result = await performLookup(trimmed)
    if (result) {
      // Persist the canonical URL and any current branch draft.
      const patch: { repo_url: string; repo_branch?: string | null } = {
        repo_url: result.repo_url,
      }
      const branch = branchDraft.trim()
      if (branch) patch.repo_branch = branch
      else patch.repo_branch = obj.repo_branch ?? null
      onChange(patch)
      // Reflect the canonical form in the input.
      setUrlDraft(result.repo_url)
    }
  }

  const handleBranchBlur = () => {
    const trimmed = branchDraft.trim()
    if (trimmed === (obj.repo_branch ?? '')) return
    onChange({ repo_branch: trimmed || null })
  }

  return (
    <div data-testid="github-repo-field">
      <SectionLabel className="mb-1.5">GitHub repo</SectionLabel>
      <div className="space-y-2">
        <div className="relative">
          <input
            type="text"
            value={urlDraft}
            onChange={(e) => {
              setUrlDraft(e.target.value)
              setValidationOk(null)
              setValidationErr(null)
            }}
            onBlur={handleUrlBlur}
            disabled={inputDisabled}
            placeholder="https://github.com/owner/name"
            spellCheck={false}
            autoComplete="off"
            data-testid="github-repo-url-input"
            title={
              !tokenLinked && !tokenLoading && !noTokenAccess
                ? 'Add a GitHub token in workspace settings to enable repo links'
                : undefined
            }
            className="bg-surface border border-border-base text-text-2 text-[12.5px] rounded-md px-2.5 py-1.5 w-full font-mono outline-none focus:border-coral disabled:opacity-50 disabled:cursor-not-allowed"
          />
          {lookup.isPending && (
            <span
              data-testid="github-repo-lookup-loading"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[10.5px] text-text-3 font-mono"
            >
              checking…
            </span>
          )}
        </div>

        {validationOk && (
          <div
            data-testid="github-repo-valid"
            className="flex items-start gap-2 text-[11.5px] text-emerald-400"
          >
            <span aria-hidden>✓</span>
            <span className="flex-1 truncate">
              {validationOk.full_name}
              {validationOk.description && (
                <span className="text-text-3"> — {validationOk.description}</span>
              )}
            </span>
          </div>
        )}
        {validationErr && (
          <div
            data-testid="github-repo-invalid"
            className="flex items-start gap-2 text-[11.5px] text-red-400"
          >
            <span aria-hidden>✗</span>
            <span className="flex-1">{validationErr}</span>
          </div>
        )}
        {!tokenLinked && !tokenLoading && !noTokenAccess && (
          <div className="text-[11px] text-text-3">
            Add a GitHub token in{' '}
            <a className="text-accent-blue hover:underline" href="/settings">
              workspace settings
            </a>{' '}
            to validate repo links.
          </div>
        )}

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-[11px] text-text-3 hover:text-text-2 transition-colors"
        >
          {showAdvanced ? '− Hide advanced' : '+ Show advanced'}
        </button>

        {showAdvanced && (
          <div>
            <SectionLabel className="mb-1.5">Branch (optional)</SectionLabel>
            <input
              type="text"
              value={branchDraft}
              onChange={(e) => setBranchDraft(e.target.value)}
              onBlur={handleBranchBlur}
              disabled={inputDisabled}
              placeholder="main"
              data-testid="github-repo-branch-input"
              className="bg-surface border border-border-base text-text-2 text-[12.5px] rounded-md px-2.5 py-1.5 w-full font-mono outline-none focus:border-coral disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
        )}
      </div>
    </div>
  )
}
