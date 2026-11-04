// HTML widget: an extension's widget.html drawn in a sandboxed iframe (scripts allowed, no same-origin -> no
// cookies, no access to the app or its API). The server serves it as its own document (`/ext/<id>/widget-frame`:
// an srcdoc frame would inherit the app's strict script policy), with a tiny bridge first (WIDGET_BRIDGE in
// server/maxxing/api/extensions.py); the theme goes in the URL fragment, then by message:
//   maxxing.api(path, {method, body, query}) -> Promise   (calls the extension's own api.py handle())
//   maxxing.resize(px) · maxxing.theme ('dark'|'light') · maxxing.onTheme(fn)
// A host may give more (`host`, the Office views of the Agents page, features/agents/OfficeCustom.tsx):
//   maxxing.data + maxxing.onData(fn)   what the host pushes (again at every change)
//   maxxing.app(path, {query})          a read-only GET of the app API, only the exact paths of `host.reads`
//   maxxing.navigate(route)             an app route starting with one of `host.routes`
// Elsewhere (the dashboard) app() is refused and navigate() ignored.
// and the app's theme variables (--background, --card, --primary, --border… and the older --mx-bg --mx-card --mx-fg
// --mx-muted --mx-border --mx-accent) follow the app theme; the UI kit (`ui-*` classes) is inlined by the server.
import * as React from 'react'
import { TriangleAlert } from 'lucide-react'
import { useNavigate } from 'react-router'
import { request, seg } from '@/lib/api'
import { useUI, resolveTheme } from '@/stores/ui'
import { useT } from '@/i18n'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'

const VARS: [string, string][] = [
  ['--mx-bg', '--background'],
  ['--mx-card', '--card'],
  ['--mx-fg', '--foreground'],
  ['--mx-muted', '--muted-foreground'],
  ['--mx-border', '--border'],
  ['--mx-accent', '--primary'],
  // the same names as the app, for the UI kit (server/maxxing/assets/ui-kit.css) and the widget's own CSS
  ...[
    'background', 'foreground', 'card', 'card-foreground', 'muted', 'muted-foreground', 'accent', 'accent-foreground',
    'primary', 'primary-foreground', 'secondary', 'secondary-foreground', 'destructive', 'destructive-foreground',
    'success', 'warning', 'border', 'input', 'ring', 'radius', 'row-h', 'pad-card',
  ].map((n): [string, string] => [`--${n}`, `--${n}`]),
]

function themeVars(): Record<string, string> {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(VARS.map(([k, v]) => [k, cs.getPropertyValue(v).trim()]))
}

// A path from the frame, made safe to append to /api/ext/<id>/: each segment encoded, '.' / '..'
// refused (also their percent-encoded forms), so a widget can only reach its own extension's API.
function extPath(raw: unknown): string {
  const parts = String(raw ?? '').replace(/^\/+/, '').split('/')
  return parts
    .map((p) => {
      let d = p
      try {
        d = decodeURIComponent(p)
      } catch {
        /* keep it as typed */
      }
      if (d.trim() === '.' || d.trim() === '..') throw new Error('Invalid path')
      return encodeURIComponent(d)
    })
    .join('/')
}

/** What a page that frames an extension gives it besides its own API (see the top of this file). */
export type FrameHost = {
  /** paths of the app API the frame may read with GET, e.g. /api/agents */
  reads?: string[]
  /** route prefixes maxxing.navigate() may open, e.g. /agents */
  routes?: string[]
  /** pushed to the frame (plain JSON) at load and whenever it changes */
  data?: unknown
}

/** `route` is an app route under one of `prefixes` (never another site, `//host`, nor a `..` that climbs out). */
function allowedRoute(route: unknown, prefixes: string[]): route is string {
  if (typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//') || /[\\\s]/.test(route)) return false
  // Checked on what the browser will make of it: `/agents/%2e%2e/settings` is `/settings`.
  let url: URL
  try {
    url = new URL(route, window.location.origin)
  } catch {
    return false
  }
  const path = url.pathname
  if (url.origin !== window.location.origin || /%2e|%2f|%5c/i.test(path) || path.split('/').some((s) => s === '.' || s === '..')) return false
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`))
}

export function HtmlWidget({
  id,
  src,
  height,
  title,
  frame: frameUrl,
  host,
  maxHeight = 1200,
  className,
}: {
  id: string
  src: string
  height: number
  title: string
  /** the frame document (default: widget.html -> widget-frame) */
  frame?: string
  host?: FrameHost
  maxHeight?: number
  className?: string
}) {
  const t = useT()
  const navigate = useNavigate()
  const hostRef = React.useRef(host)
  hostRef.current = host
  const theme = resolveTheme(useUI((s) => s.theme))
  const look = useUI((s) => `${s.accent}.${s.tint}.${s.density}`)
  const frame = React.useRef<HTMLIFrameElement>(null)
  const [loaded, setLoaded] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [h, setH] = React.useState(height)
  // The frame URL is fixed at mount (theme changes go by message): a new fragment would not reload it anyway.
  const [frameSrc] = React.useState(
    () => `${frameUrl || src.replace(/widget\.html$/, 'widget-frame')}#${encodeURIComponent(JSON.stringify({ theme: resolveTheme(useUI.getState().theme), vars: themeVars() }))}`,
  )

  // A missing or disabled widget: say so instead of an empty frame (HEAD: the frame downloads the page itself).
  React.useEffect(() => {
    let cancelled = false
    setError(null)
    fetch(src, { credentials: 'same-origin', method: 'HEAD' })
      .then((r) => !cancelled && !r.ok && setError(`HTTP ${r.status}`))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
  }, [src])

  // Bridge: API calls (to this extension only), resize.
  React.useEffect(() => {
    const onMsg = async (e: MessageEvent) => {
      const win = frame.current?.contentWindow
      if (!win || e.source !== win) return
      const m = (e.data || {}) as { mx?: string; seq?: number; path?: string; method?: string; body?: unknown; query?: Record<string, string>; height?: number }
      if (m.mx === 'resize' && typeof m.height === 'number') setH(Math.min(maxHeight, Math.max(80, Math.round(m.height))))
      if (m.mx === 'navigate') {
        const r = (m as { route?: unknown }).route
        if (allowedRoute(r, hostRef.current?.routes || [])) navigate(r)
      }
      if (m.mx === 'app') {
        const path = String(m.path || '')
        if (!(hostRef.current?.reads || []).includes(path)) {
          win.postMessage({ mx: 'reply', seq: m.seq, ok: false, error: `${path || 'this path'} is not readable from here` }, '*')
          return
        }
        try {
          const data = await request(path, { method: 'GET', query: m.query })
          win.postMessage({ mx: 'reply', seq: m.seq, ok: true, data }, '*')
        } catch (err) {
          win.postMessage({ mx: 'reply', seq: m.seq, ok: false, error: err instanceof Error ? err.message : String(err) }, '*')
        }
      }
      if (m.mx === 'api') {
        const up = (m.method || 'GET').toUpperCase()
        const method = (['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(up) ? up : 'GET') as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
        try {
          const data = await request(`/api/ext/${seg(id)}/${extPath(m.path)}`, {
            method,
            body: method === 'GET' ? undefined : (m.body ?? {}),
            query: m.query,
          })
          win.postMessage({ mx: 'reply', seq: m.seq, ok: true, data }, '*')
        } catch (err) {
          win.postMessage({ mx: 'reply', seq: m.seq, ok: false, error: err instanceof Error ? err.message : String(err) }, '*')
        }
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [id, maxHeight, navigate])

  // The host's data: at load (a message sent before would reach the blank document) and at every change.
  const data = host?.data
  const push = React.useCallback(() => data !== undefined && frame.current?.contentWindow?.postMessage({ mx: 'data', data }, '*'), [data])
  React.useEffect(() => {
    if (loaded) push()
  }, [loaded, push])

  React.useEffect(() => {
    // after the <html> attributes changed (accent, tint, density set them in an effect too)
    const r = requestAnimationFrame(() => frame.current?.contentWindow?.postMessage({ mx: 'theme', theme, vars: themeVars() }, '*'))
    return () => cancelAnimationFrame(r)
  }, [theme, look])

  if (error)
    return (
      <div className="flex min-h-24 flex-col items-center justify-center gap-2 text-center">
        <TriangleAlert className="size-5 text-destructive" />
        <p className="text-[13px] text-muted-foreground">
          {t('ext.loadFailed')} ({error})
        </p>
      </div>
    )
  return (
    <div className={cn('relative', className)} style={{ height: h }}>
      {!loaded && <Skeleton className="absolute inset-0 rounded-lg" />}
      <iframe
        ref={frame}
        title={title}
        src={frameSrc}
        onLoad={() => {
          setLoaded(true)
          push()
        }}
        sandbox="allow-scripts allow-pointer-lock"
        referrerPolicy="no-referrer"
        className={cn('block size-full rounded-lg border-0 bg-transparent transition-opacity duration-200', loaded ? 'opacity-100' : 'opacity-0')}
      />
    </div>
  )
}
