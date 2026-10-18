import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useSession } from '../lib/session'
import { ErrorMessage } from './Feedback'

/** Client-side redirect only; every protected API route is enforced by the server. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession()
  const location = useLocation()
  if (session.isPending) return <p>Checking sign-in…</p>
  if (session.isError) return <ErrorMessage error={session.error} />
  if (!session.data) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}
