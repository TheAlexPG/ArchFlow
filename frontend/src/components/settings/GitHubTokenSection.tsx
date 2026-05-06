import { useState } from 'react'
import {
  useClearGitHubToken,
  useGitHubTokenStatus,
  useSetGitHubToken,
  useTestGitHubToken,
} from '../../hooks/use-api'
import { useWorkspaceStore } from '../../stores/workspace-store'

interface ApiError {
  response?: { data?: { detail?: { error?: string; message?: string } | string } }
}

function describeError(err: unknown, fallback: string): string {
  const e = err as ApiError | undefined
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    return detail.message ?? detail.error ?? fallback
  }
  return fallback
}

export function GitHubTokenSection() {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId)
  const status = useGitHubTokenStatus(workspaceId)
  const setToken = useSetGitHubToken(workspaceId)
  const testToken = useTestGitHubToken(workspaceId)
  const clearToken = useClearGitHubToken(workspaceId)

  const [pat, setPat] = useState('')
  const [showSecret, setShowSecret] = useState(false)
  const [inlineError, setInlineError] = useState<string | null>(null)
  const [inlineNotice, setInlineNotice] = useState<string | null>(null)

  const linked = status.data?.linked === true
  const login = status.data?.github_login ?? null

  // The status query 403/404s for non-owners. Fall back to read-only display.
  const accessDenied = status.isError

  const handleSave = async () => {
    setInlineError(null)
    setInlineNotice(null)
    if (!pat.trim()) {
      setInlineError('Paste a Personal Access Token first.')
      return
    }
    try {
      await setToken.mutateAsync(pat.trim())
      setInlineNotice('Token saved.')
      setPat('')
      setShowSecret(false)
    } catch (err) {
      setInlineError(describeError(err, 'Could not save token.'))
    }
  }

  const handleTest = async () => {
    setInlineError(null)
    setInlineNotice(null)
    try {
      const tokenToTest = pat.trim() ? pat.trim() : null
      const res = await testToken.mutateAsync(tokenToTest)
      if (res.linked) {
        setInlineNotice(
          `Token is valid${
            res.github_login ? ` (logged in as ${res.github_login})` : ''
          }.`,
        )
      } else {
        setInlineError('GitHub did not accept this token.')
      }
    } catch (err) {
      setInlineError(describeError(err, 'Could not reach GitHub.'))
    }
  }

  const handleClear = async () => {
    if (!confirm('Remove the workspace GitHub token?')) return
    setInlineError(null)
    setInlineNotice(null)
    try {
      await clearToken.mutateAsync()
      setInlineNotice('Token removed.')
    } catch (err) {
      setInlineError(describeError(err, 'Could not clear token.'))
    }
  }

  return (
    <section className="max-w-3xl mb-10">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold">GitHub</h2>
          <p className="text-xs text-neutral-500 mt-0.5">
            A Personal Access Token (read-only on the repos you want to link)
            unlocks GitHub repo links on Container/System nodes and the
            repo-aware AI features.
          </p>
        </div>
        <div className="text-xs">
          {accessDenied ? (
            <span className="text-neutral-500 italic">
              Owner-only setting
            </span>
          ) : status.isLoading ? (
            <span className="text-neutral-500 italic">Loading…</span>
          ) : linked ? (
            <span className="text-emerald-400">
              Linked
              {login && (
                <>
                  {' '}
                  · <code className="font-mono text-emerald-300">{login}</code>
                </>
              )}
            </span>
          ) : (
            <span className="text-neutral-500">Not linked</span>
          )}
        </div>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 rounded-lg p-5 space-y-3">
        {accessDenied ? (
          <div className="text-xs text-neutral-400">
            Only workspace owners can configure the GitHub token.
          </div>
        ) : (
          <>
            <label className="block text-xs text-neutral-400 mb-1">
              Personal Access Token
            </label>
            <div className="flex items-stretch gap-2">
              <input
                type={showSecret ? 'text' : 'password'}
                value={pat}
                onChange={(e) => setPat(e.target.value)}
                placeholder="ghp_…"
                autoComplete="off"
                spellCheck={false}
                className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm font-mono outline-none focus:border-neutral-500"
              />
              <button
                type="button"
                onClick={() => setShowSecret((v) => !v)}
                className="bg-neutral-700 hover:bg-neutral-600 text-xs rounded px-3"
              >
                {showSecret ? 'Hide' : 'Show'}
              </button>
            </div>

            {inlineError && (
              <div className="text-xs text-red-400">{inlineError}</div>
            )}
            {inlineNotice && (
              <div className="text-xs text-emerald-400">{inlineNotice}</div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              {linked && (
                <button
                  onClick={handleClear}
                  disabled={clearToken.isPending}
                  className="text-xs text-red-400 hover:text-red-300 px-3 py-1.5 disabled:opacity-40"
                >
                  {clearToken.isPending ? 'Clearing…' : 'Clear'}
                </button>
              )}
              <button
                onClick={handleTest}
                disabled={testToken.isPending}
                className="bg-neutral-700 hover:bg-neutral-600 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
              >
                {testToken.isPending ? 'Testing…' : 'Test'}
              </button>
              <button
                onClick={handleSave}
                disabled={setToken.isPending || !pat.trim()}
                className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded px-3 py-1.5 disabled:opacity-40"
              >
                {setToken.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
