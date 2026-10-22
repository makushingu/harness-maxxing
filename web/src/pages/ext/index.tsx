// /x/:id — extension pages. Loads /ext/<id>/page.js (ES module) and calls mount(el, ctx).
// ctx = { api(path, {method, body}), navigate(route), theme: 'dark'|'light', lang: 'en'|'fr', t(key), icon(name) }
// The page is mounted inside `.mx-ext`, where the shared UI kit (`/ext/ui-kit.css`, `ui-*` classes) applies.
//   ctx.api('notes') → /api/ext/<id>/notes, JSON body + X-Maxxing header on non-GET, resolves to parsed JSON,
//   rejects with an Error on HTTP errors.
import * as React from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { useNavigate, useParams } from 'react-router'
import { Pin, PinOff, Puzzle, TriangleAlert } from 'lucide-react'
import { request, seg } from '@/lib/api'
import { useExtensions, usePinExtension } from '@/lib/queries'
import { useUI, resolveTheme } from '@/stores/ui'
import { useLang, useT, tDyn } from '@/i18n'
import { Button, EmptyState, NamedIcon, SkeletonText, Tooltip } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'

type Mount = (el: HTMLElement, ctx: ExtensionContext) => void | (() => void)
export type ExtensionContext = {
  id: string
  api: <T = unknown>(path: string, opts?: { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; body?: unknown; query?: Record<string, string | number> }) => Promise<T>
  navigate: (to: string) => void
  theme: 'dark' | 'light'
  /** the UI language */
  lang: string
  t: (key: string) => string
  /** an icon of the app (kebab-case lucide name, the curated set of NamedIcon; unknown -> puzzle) as an <svg> */
  icon: (name: string, opts?: { size?: number; className?: string }) => SVGElement
}

/** The UI kit stylesheet, added once to the document (pages share it, it stays for the next visit). */
function useUiKit() {
  React.useEffect(() => {
    if (document.getElementById('mx-ui-kit')) return
    const link = document.createElement('link')
    link.id = 'mx-ui-kit'
    link.rel = 'stylesheet'
    link.href = '/ext/ui-kit.css'
    document.head.append(link)
  }, [])
}

const iconCache = new Map<string, SVGElement>()
function iconSvg(name: string, opts: { size?: number; className?: string } = {}): SVGElement {
  const key = String(name || '')
  let svg = iconCache.get(key)
  if (!svg) {
    const box = document.createElement('span')
    const root = createRoot(box)
    flushSync(() => root.render(<NamedIcon name={key} aria-hidden="true" />))
    svg = box.querySelector('svg') as SVGElement
    root.unmount()
    iconCache.set(key, svg)
  }
  const out = svg.cloneNode(true) as SVGElement
  out.setAttribute('class', ['ui-icon', opts.className].filter(Boolean).join(' '))
  if (opts.size) {
    out.setAttribute('width', String(opts.size))
    out.setAttribute('height', String(opts.size))
    out.style.width = out.style.height = `${opts.size}px`
  }
  return out
}

export default function ExtensionPage() {
  const t = useT()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const theme = resolveTheme(useUI((s) => s.theme))
  const lang = useLang()
  const { data: exts } = useExtensions()
  const ext = exts?.find((e) => e.id === id)
  const pin = usePinExtension()
  const host = React.useRef<HTMLDivElement>(null)
  const [state, setState] = React.useState<{ status: 'loading' | 'ready' | 'error'; error?: string }>({ status: 'loading' })
  const [attempt, setAttempt] = React.useState(0)
  useUiKit()

  // The extensions list is a shell query (there at boot): wait for it to know page.js's version.
  const version = exts ? (ext?.page_v ?? 0) : null
  React.useEffect(() => {
    const el = host.current
    if (!el || !id || version === null) return
    let cleanup: void | (() => void)
    let cancelled = false
    setState({ status: 'loading' })
    const ctx: ExtensionContext = {
      id,
      api: (path, opts = {}) =>
        request(`/api/ext/${seg(id)}/${path.replace(/^\/+/, '')}`, { method: opts.method || 'GET', body: opts.method && opts.method !== 'GET' ? (opts.body ?? {}) : undefined, query: opts.query }),
      navigate: (to) => navigate(to),
      theme,
      lang,
      t: (key) => tDyn(t, key),
      icon: iconSvg,
    }
    // Versioned by page.js's mtime: the module is downloaded and evaluated once, an edited file gets a new URL.
    // A retry (attempt) always fetches it again.
    const url = `/ext/${encodeURIComponent(id)}/page.js?v=${version || Date.now()}${attempt ? `-${attempt}` : ''}`
    import(/* @vite-ignore */ url)
      .then((mod: { mount?: Mount; default?: { mount?: Mount } }) => {
        if (cancelled) return
        const mount = mod.mount || mod.default?.mount
        if (typeof mount !== 'function') throw new Error(t('ext.noMount'))
        el.replaceChildren()
        cleanup = mount(el, ctx)
        setState({ status: 'ready' })
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) })
      })
    return () => {
      cancelled = true
      try {
        if (typeof cleanup === 'function') cleanup()
      } catch {
        /* extension cleanup errors are ignored */
      }
      el.replaceChildren()
    }
  }, [id, version, theme, lang, navigate, t, attempt])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={ext?.name || id}
        actions={
          ext?.type === 'page' && (
            <Tooltip content={ext.pinned ? t('ext.unpin') : t('ext.pin')}>
              <Button
                variant="ghost"
                size="icon-sm"
                className={ext.pinned ? 'text-primary' : 'text-muted-foreground'}
                aria-label={ext.pinned ? t('ext.unpin') : t('ext.pin')}
                aria-pressed={!!ext.pinned}
                onClick={() => pin.mutate({ id: ext.id, pinned: !ext.pinned })}
              >
                {ext.pinned ? <PinOff /> : <Pin />}
              </Button>
            </Tooltip>
          )
        }
      />
      <div className="relative flex-1 px-4 py-6 md:px-6">
        {state.status === 'loading' && (
          <div className="absolute inset-x-4 top-6 md:inset-x-6">
            <SkeletonText lines={6} className="max-w-2xl" />
          </div>
        )}
        {state.status === 'error' && (
          <EmptyState
            icon={ext ? TriangleAlert : Puzzle}
            tone={ext ? 'error' : 'default'}
            title={ext ? t('ext.loadFailed') : t('ext.notFound')}
            description={<span className="font-mono text-xs break-all">{state.error}</span>}
            action={<Button onClick={() => setAttempt((a) => a + 1)}>{t('common.retry')}</Button>}
          />
        )}
        <div ref={host} className="mx-ext" hidden={state.status === 'error'} />
      </div>
    </div>
  )
}
