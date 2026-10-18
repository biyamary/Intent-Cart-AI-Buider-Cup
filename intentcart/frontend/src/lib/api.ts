import { idToken } from './firebase'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

let unauthorized: (() => void) | undefined
/** Called whenever the API rejects the current sign-in (missing or expired session). */
export function onUnauthorized(handler: () => void) {
  unauthorized = handler
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await idToken()
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${base}/api${path}`, { ...options, headers })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401) unauthorized?.()
    const detail = data?.detail
    throw new ApiError(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join('; ')
          : `Request failed (${response.status}).`,
      response.status,
    )
  }
  return data as T
}
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

/** Fetch a protected image as an object URL; the caller must revoke it. */
export async function apiObjectUrl(path: string): Promise<string> {
  const token = await idToken()
  const response = await fetch(`${base}/api${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (response.status === 401) unauthorized?.()
  if (!response.ok) throw new Error(`Image unavailable (${response.status}).`)
  return URL.createObjectURL(await response.blob())
}

export async function upload<T>(path: string, field: string, file: File): Promise<T> {
  const form = new FormData()
  form.append(field, file)
  return api<T>(path, { method: 'POST', body: form })
}
