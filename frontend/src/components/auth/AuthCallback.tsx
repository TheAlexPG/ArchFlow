import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/auth-store'

// Lands here after the backend redirects us back from Google with tokens in
// the URL fragment (#access_token=...&refresh_token=...). Fragment parsing
// keeps tokens out of server access logs — they never hit the network path.
export function AuthCallback() {
  const navigate = useNavigate()
  const setTokens = useAuthStore((s) => s.setTokens)

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, '')
    const params = new URLSearchParams(hash)
    const access = params.get('access_token')
    const refresh = params.get('refresh_token')
    if (access && refresh) {
      setTokens(access, refresh)
      // Wipe the fragment so tokens don't linger in browser history.
      window.history.replaceState({}, document.title, '/')
      navigate('/', { replace: true })
    } else {
      navigate('/login?error=oauth', { replace: true })
    }
  }, [navigate, setTokens])

  return (
    <div className="flex h-screen items-center justify-center bg-neutral-950 text-neutral-400 text-sm">
      Signing you in…
    </div>
  )
}
