import { useQuery, type QueryClient } from '@tanstack/react-query'
import { api, ApiError, post } from './api'
import { auth, logOut } from './firebase'
import { useLookStore } from '../store/lookStore'

export interface SessionUser {
  id: string
  name: string
  auth_mode: 'demo' | 'static' | 'firebase'
}

export const sessionKey = ['auth-session'] as const

/** The signed-in user, or null. The server decides; the browser only asks. */
export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: () =>
      api<SessionUser>('/auth/me').catch((error) => {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

/** Drop everything cached for the previous user. */
export function clearUserData(cache: QueryClient) {
  cache.removeQueries({ predicate: (query) => query.queryKey[0] !== sessionKey[0] })
  useLookStore.getState().setLook(null)
}

export function switchUser(cache: QueryClient, user: SessionUser | null) {
  clearUserData(cache)
  cache.setQueryData(sessionKey, user)
}

export async function signOut(cache: QueryClient) {
  if (auth) await logOut()
  else await post('/auth/logout')
  switchUser(cache, null)
}
