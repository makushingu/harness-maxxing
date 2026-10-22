// Typed fetch client for the Harness Maxxing API (docs/dev/API.md).
// - same-origin cookies, JSON in/out
// - every non-GET request carries `X-Maxxing: 1` (CSRF)
// - errors throw ApiError {status, code, message}
// - 401 `auth_required` on a protected endpoint → onUnauthorized() (the app redirects to /login?next=…)

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message?: string) {
    super(message || code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function isApiError(e: unknown, code?: string): e is ApiError {
  return e instanceof ApiError && (code === undefined || e.code === code)
}

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message || e.code
  if (e instanceof Error) return e.message
  return String(e)
}

type Query = Record<string, string | number | boolean | null | undefined>

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Query
  signal?: AbortSignal
  /** Do not trigger the global 401 redirect (auth endpoints, login form…). */
  noAuthRedirect?: boolean
  headers?: Record<string, string>
}

let unauthorizedHandler: (() => void) | null = null
/** Registered once by the app (router-aware redirect). */
export function onUnauthorized(fn: () => void) {
  unauthorizedHandler = fn
}

export function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue
    qs.set(k, typeof v === 'boolean' ? (v ? '1' : '0') : String(v))
  }
  const s = qs.toString()
  return s ? `${path}${path.includes('?') ? '&' : '?'}${s}` : path
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method || 'GET'
  const headers: Record<string, string> = { Accept: 'application/json', ...opts.headers }
  let body: BodyInit | undefined
  if (method !== 'GET') headers['X-Maxxing'] = '1'
  if (opts.body instanceof FormData) {
    body = opts.body
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(withQuery(path, opts.query), {
      method,
      headers,
      body,
      credentials: 'same-origin',
      signal: opts.signal,
      cache: 'no-store',
    })
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, 'network', 'Network error — the server could not be reached.')
  }
  const text = await res.text()
  let data: unknown = undefined
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    const d = (data && typeof data === 'object' ? data : {}) as { error?: string; message?: string }
    const err = new ApiError(res.status, d.error || `http_${res.status}`, d.message || (typeof data === 'string' ? data.slice(0, 200) : res.statusText))
    // Only our own sign-in check signs out (`auth_required`): a 401 relayed from elsewhere (an extension's API, a
    // service that refused a token) is an ordinary error, not a reason to leave the page.
    if (res.status === 401 && d.error === 'auth_required' && !opts.noAuthRedirect && unauthorizedHandler) unauthorizedHandler()
    throw err
  }
  return data as T
}

export const api = {
  get: <T>(path: string, query?: Query, o?: Omit<RequestOptions, 'method' | 'query'>) => request<T>(path, { ...o, query }),
  post: <T>(path: string, body?: unknown, o?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...o, method: 'POST', body: body ?? {} }),
  put: <T>(path: string, body?: unknown, o?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...o, method: 'PUT', body: body ?? {} }),
  patch: <T>(path: string, body?: unknown, o?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...o, method: 'PATCH', body: body ?? {} }),
  del: <T>(path: string, o?: Omit<RequestOptions, 'method'>) => request<T>(path, { ...o, method: 'DELETE' }),
  /** multipart upload (field `file`, repeated). */
  upload: <T>(path: string, files: File[] | FileList, query?: Query) => {
    const fd = new FormData()
    for (const f of Array.from(files)) fd.append('file', f, f.name)
    return request<T>(path, { method: 'POST', body: fd, query })
  },
}

/** Encode one path segment (ids, names). */
export const seg = (s: string) => encodeURIComponent(s)
