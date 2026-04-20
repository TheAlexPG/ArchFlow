import { useState } from 'react'
import axios from 'axios'
import { useAuthStore } from '../../stores/auth-store'

export function AuthPage() {
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setTokens } = useAuthStore()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const endpoint = isLogin ? '/api/v1/auth/login' : '/api/v1/auth/register'
      const payload = isLogin ? { email, password } : { email, name, password }
      const { data } = await axios.post(endpoint, payload)
      setTokens(data.access_token, data.refresh_token)
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setError(err.response.data.detail)
      } else {
        setError('Something went wrong')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleLogin = async () => {
    // Stub: the backend's /auth/oauth/google/login returns a URL that points
    // right back at its own callback with a sample code. In production this
    // would be a Google 302 we'd window.location.assign() to. For the stub
    // we just ask the user for an email and post to the callback directly.
    const email = prompt('Google OAuth stub — enter email to sign in as:')
    if (!email) return
    setError('')
    setLoading(true)
    try {
      const { data } = await axios.get('/api/v1/auth/oauth/google/callback', {
        params: { code: email },
      })
      setTokens(data.access_token, data.refresh_token)
    } catch (err: unknown) {
      const msg =
        (axios.isAxiosError(err) && err.response?.data?.detail) ||
        'OAuth stub failed'
      setError(String(msg))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-neutral-950">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold text-neutral-100 text-center mb-2">ArchFlow</h1>
        <p className="text-sm text-neutral-500 text-center mb-8">
          Architecture Design & Modeling Platform
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isLogin && (
            <input
              type="text"
              placeholder="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-3 py-2 bg-neutral-900 border border-neutral-700 rounded-lg text-neutral-200 text-sm outline-none focus:border-neutral-500"
            />
          )}
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full px-3 py-2 bg-neutral-900 border border-neutral-700 rounded-lg text-neutral-200 text-sm outline-none focus:border-neutral-500"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
            className="w-full px-3 py-2 bg-neutral-900 border border-neutral-700 rounded-lg text-neutral-200 text-sm outline-none focus:border-neutral-500"
          />

          {error && <div className="text-sm text-red-400">{error}</div>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? '...' : isLogin ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div className="flex items-center gap-3 my-4">
          <div className="flex-1 h-px bg-neutral-800" />
          <span className="text-xs text-neutral-600">or</span>
          <div className="flex-1 h-px bg-neutral-800" />
        </div>

        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={loading}
          className="w-full py-2 bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 disabled:opacity-50 text-neutral-100 rounded-lg text-sm font-medium"
          title="Stub — real Google integration wired up later"
        >
          Continue with Google (stub)
        </button>

        <p className="text-sm text-neutral-500 text-center mt-4">
          {isLogin ? "Don't have an account?" : 'Already have an account?'}{' '}
          <button
            onClick={() => { setIsLogin(!isLogin); setError('') }}
            className="text-blue-400 hover:text-blue-300"
          >
            {isLogin ? 'Sign up' : 'Sign in'}
          </button>
        </p>
      </div>
    </div>
  )
}
