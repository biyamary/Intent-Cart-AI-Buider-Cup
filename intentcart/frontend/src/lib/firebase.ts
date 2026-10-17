import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut } from 'firebase/auth'

const useFirebase = import.meta.env.VITE_AUTH_MODE === 'firebase'
export const auth = useFirebase
  ? getAuth(
      initializeApp({
        apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
        appId: import.meta.env.VITE_FIREBASE_APP_ID,
      }),
    )
  : null

export const signIn = async () => {
  if (auth) await signInWithPopup(auth, new GoogleAuthProvider())
}
export const logOut = async () => {
  if (auth) await signOut(auth)
}
export async function idToken() {
  if (!auth) return null
  await auth.authStateReady()
  return auth.currentUser?.getIdToken() ?? null
}
