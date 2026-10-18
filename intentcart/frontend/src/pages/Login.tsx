import { useState } from 'react'
import { Navigate, useLocation, type Location } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, LogIn } from 'lucide-react'
import { post } from '../lib/api'
import { auth, signIn } from '../lib/firebase'
import { switchUser, useSession, type SessionUser } from '../lib/session'
import { ErrorMessage } from '../components/Feedback'

export function Login() {
  const cache = useQueryClient()
  const session = useSession()
  const location = useLocation()
  const from = (location.state as { from?: Location } | null)?.from
  const next = from ? `${from.pathname}${from.search}${from.hash}` : '/'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: () => post<SessionUser>('/auth/login', { username, password }),
    onSuccess: (user) => switchUser(cache, user),
    onError: () => setPassword(''),
  })
  const google = useMutation({ mutationFn: signIn })

  if (session.data) return <Navigate to={next} replace />
  return (
    <div className="login-page">
      <div className="panel stack login-panel">
        <div>
          <span className="eyebrow">WELCOME BACK</span>
          <h1>Sign in to chat.</h1>
          <p>Nia and Mira keep your conversations private to your account.</p>
        </div>
        <ErrorMessage error={session.error ?? login.error ?? google.error} />
        {auth ? (
          <button disabled={google.isPending} onClick={() => google.mutate()}>
            Continue with Google <ArrowUpRight size={18} />
          </button>
        ) : (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              login.mutate()
            }}
          >
            <label>
              Username
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={64}
                required
                autoFocus
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                maxLength={256}
                required
              />
            </label>
            <button disabled={login.isPending || session.isPending}>
              <LogIn size={17} /> {login.isPending ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
