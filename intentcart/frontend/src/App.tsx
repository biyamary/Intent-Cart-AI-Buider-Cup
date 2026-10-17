import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Route, Routes, Link } from 'react-router-dom'
import { ShoppingBag, ScanLine, Shirt, UserRound, ArrowUpRight } from 'lucide-react'
import { onAuthStateChanged } from 'firebase/auth'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './lib/api'
import { auth, signIn, logOut } from './lib/firebase'
import { useLookStore } from './store/lookStore'
import { Home } from './pages/Home'
import { FoodCheck } from './pages/FoodCheck'
import { LookBoard } from './pages/LookBoard'
import { Profile } from './pages/Profile'
import { ErrorMessage } from './components/Feedback'

const ShopLook = lazy(() =>
  import('./pages/ShopLook').then((module) => ({ default: module.ShopLook })),
)

export default function App() {
  const cache = useQueryClient()
  const [uid, setUid] = useState<string | null>(auth ? null : 'demo')
  const [ready, setReady] = useState(!auth)
  const [authError, setAuthError] = useState<unknown>()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () =>
      api<{ agent_mode: string; stylist_agent_mode: string; auth_mode: string }>('/health'),
    retry: 1,
  })
  useEffect(() => {
    if (!auth) return
    return onAuthStateChanged(auth, (user) => {
      cache.clear()
      useLookStore.getState().setLook(null)
      setUid(user?.uid ?? null)
      setReady(true)
    })
  }, [cache])
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
          <NavLink className="profile-link" to="/profile">
            <UserRound size={18} />
            <span>My profile</span>
          </NavLink>
        </div>
      </header>
      <div className="app-mode">
        {health.isError
          ? 'API unavailable · Start the backend on port 8000'
          : health.data
            ? health.data.stylist_agent_mode === 'gemini'
              ? 'Shop a look · Gemini with Google Search'
              : health.data.agent_mode === 'demo'
                ? 'Local demo · Sample data and placeholder AI responses'
                : 'Gemini mode · Prompts and integrations require configuration'
            : 'Connecting to your companion…'}
        {auth && (
          <button
            className="text-button"
            onClick={() => {
              setAuthError(null)
              void (uid ? logOut() : signIn()).catch(setAuthError)
            }}
          >
            {uid ? 'Sign out' : 'Sign in with Google'}
          </button>
        )}
      </div>
      <main className="main">
        <ErrorMessage error={authError} />
        {!ready ? (
          <p>Checking sign-in…</p>
        ) : !uid ? (
          <div className="panel stack">
            <h1>Welcome to IntentCart.</h1>
            <p>Sign in to save your preferences, food reviews, and looks.</p>
            <button
              onClick={() => {
                void signIn().catch(setAuthError)
              }}
            >
              Continue with Google <ArrowUpRight size={18} />
            </button>
          </div>
        ) : (
          <Routes key={uid}>
            <Route path="/" element={<Home />} />
            <Route path="/food" element={<FoodCheck />} />
            <Route
              path="/clothes"
              element={
                <Suspense fallback={<p>Loading your stylist…</p>}>
                  <ShopLook />
                </Suspense>
              }
            />
            <Route path="/clothes/board" element={<LookBoard />} />
            <Route path="/profile" element={<Profile />} />
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
        )}
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
