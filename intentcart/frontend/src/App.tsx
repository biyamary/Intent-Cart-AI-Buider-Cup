import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Route, Routes, Link, useNavigate } from 'react-router-dom'
import { ShoppingBag, ScanLine, Shirt, UserRound, LogIn, LogOut } from 'lucide-react'
import { onAuthStateChanged } from 'firebase/auth'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, onUnauthorized } from './lib/api'
import { auth } from './lib/firebase'
import { clearUserData, sessionKey, signOut, switchUser, useSession } from './lib/session'
import { Home } from './pages/Home'
import { FoodCheck } from './pages/FoodCheck'
import { LookBoard } from './pages/LookBoard'
import { Login } from './pages/Login'
import { Profile } from './pages/Profile'
import { ErrorMessage } from './components/Feedback'
import { RequireAuth } from './components/RequireAuth'

const ShopLook = lazy(() =>
  import('./pages/ShopLook').then((module) => ({ default: module.ShopLook })),
)

export default function App() {
  const cache = useQueryClient()
  const navigate = useNavigate()
  const session = useSession()
  const user = session.data
  const [authError, setAuthError] = useState<unknown>()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () =>
      api<{ agent_mode: string; stylist_agent_mode: string; food_agent_mode: string; auth_mode: string }>('/health'),
    retry: 1,
  })
  useEffect(() => {
    // An expired or revoked session anywhere sends protected pages back to sign-in.
    onUnauthorized(() => {
      if (cache.getQueryData(sessionKey)) switchUser(cache, null)
    })
    if (!auth) return
    return onAuthStateChanged(auth, () => {
      clearUserData(cache)
      void cache.invalidateQueries({ queryKey: sessionKey })
    })
  }, [cache])
  // Only surface the mode bar when something needs the user's attention.
  const liveAgents =
    health.data?.food_agent_mode === 'gemini' || health.data?.stylist_agent_mode === 'gemini'
  const modeNotice = health.isError
    ? 'API unavailable · Start the backend on port 8000'
    : !health.data || liveAgents
      ? null
      : health.data.agent_mode === 'demo'
        ? 'Local demo · Sample data and placeholder AI responses'
        : 'Gemini mode · Prompts and integrations require configuration'
  return (
    <>
      <header className="site-header">
        <div className="nav-inner">
          <Link className="brand" to="/">
            <span className="brand-mark">
              <ShoppingBag size={20} />
            </span>
            intentcart<span className="brand-period">.</span>
          </Link>
          <nav aria-label="Main navigation">
            <NavLink to="/food">
              <ScanLine size={16} />
              Food
            </NavLink>
            <NavLink to="/clothes">
              <Shirt size={16} />
              Clothes
            </NavLink>
          </nav>
          <div className="account">
            <NavLink className="profile-link" to="/profile">
              <UserRound size={18} />
              <span>{user && user.auth_mode !== 'demo' ? user.name : 'My profile'}</span>
            </NavLink>
            {user && user.auth_mode !== 'demo' ? (
              <button
                className="text-button account-action"
                onClick={() => {
                  setAuthError(null)
                  signOut(cache)
                    .then(() => navigate('/'))
                    .catch(setAuthError)
                }}
              >
                <LogOut size={15} /> Sign out
              </button>
            ) : (
              !user &&
              !session.isPending && (
                <Link className="account-action" to="/login">
                  <LogIn size={15} /> Sign in
                </Link>
              )
            )}
          </div>
        </div>
      </header>
      {modeNotice && <div className="app-mode">{modeNotice}</div>}
      <main className="main">
        <ErrorMessage error={authError} />
        <Routes key={user?.id ?? 'signed-out'}>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="/food"
            element={
              <RequireAuth>
                <FoodCheck />
              </RequireAuth>
            }
          />
          <Route
            path="/clothes"
            element={
              <RequireAuth>
                <Suspense fallback={<p>Loading your stylist…</p>}>
                  <ShopLook />
                </Suspense>
              </RequireAuth>
            }
          />
          <Route
            path="/clothes/board"
            element={
              <RequireAuth>
                <LookBoard />
              </RequireAuth>
            }
          />
          <Route
            path="/profile"
            element={
              <RequireAuth>
                <Profile />
              </RequireAuth>
            }
          />
          <Route
            path="*"
            element={
              <div className="panel">
                <h1>Page not found.</h1>
                <Link to="/">Back to IntentCart</Link>
              </div>
            }
          />
        </Routes>
      </main>
      <footer>
        <Link className="brand footer-brand" to="/">
          intentcart.
        </Link>
        <span>A little more thought in every cart.</span>
        <span>Food & style, with you in mind.</span>
      </footer>
    </>
  )
}
