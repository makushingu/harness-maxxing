// The live view of one profile of the Harness Browser (WS /api/browser/live?profile=), drawn as a browser window: its
// tabs (a dot on the ones Claude opened), a toolbar with the address, the page as pictures (JPEG frames) and a status
// bar (memory, Stop). The person drives the tab shown as soon as they click or type; on a tab Claude is using right
// now, a first click takes over (Claude's commands on that tab then wait). What Claude asked shows as an info bar with
// "Hand back to Claude". Coordinates are sent as 0..1 of the picture: the server maps them to the page's size.
// Pace: each picture is confirmed ({"t":"got"}) once drawn, and the server sends the next one only then (a slow network
// gets fewer pictures, never late ones). The wheel is summed and sent at most once per picture; the picture moves
// at once by what was scrolled (the real one follows).
import * as React from 'react'
import {
  ArrowLeft, ArrowRight, Gauge, Globe, Hand, Keyboard, Loader2, Lock, Minus, Moon, MousePointerClick,
  Plus, RotateCw, SkipForward, Square, X,
} from 'lucide-react'
import { useT } from '@/i18n'
import { browserLiveToken, useAnswerAsk, useBrowserProfile, useBrowserTab, useProfileAction } from '@/lib/queries'
import type { BrowserAsk, BrowserState, BrowserTab } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { useCompact } from '@/stores/media'
import { cn } from '@/lib/utils'
import { Button, Input } from '@/components/ui'
import { tabOfSession } from './profiles'

type LiveState = { browser: BrowserState | null; me: boolean; asks: BrowserAsk[] }
/** What the pictures cost, measured here (the "speed" button of the status bar). */
type Pace = { fps: number; kb: number; delay: number | null }

/** The WebSocket of the live view: pictures + state; reconnects while mounted. */
function useLive(active: boolean, profile: string, onFrame?: () => void) {
  const compact = useCompact()
  const [frame, setFrame] = React.useState(false)
  const img = React.useRef<HTMLImageElement | null>(null)
  const [state, setState] = React.useState<LiveState | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [connected, setConnected] = React.useState(false)
  const ws = React.useRef<WebSocket | null>(null)
  const url = React.useRef<string | null>(null)
  const frameCb = React.useRef(onFrame)
  frameCb.current = onFrame
  // the pace, for the status bar: pictures in the last 2 s, their mean size, the delay after an input
  const pace = React.useRef({ times: [] as number[], bytes: [] as number[], inputAt: 0, delay: null as number | null })

  React.useEffect(() => {
    if (!active) return
    let stop = false
    let retry = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    const open = async () => {
      if (stop) return
      let token = ''
      try {
        token = (await browserLiveToken()).token
      } catch {
        timer = setTimeout(open, Math.min(15000, 1000 * 2 ** retry++))
        return
      }
      if (stop) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const s = new WebSocket(`${proto}://${location.host}/api/browser/live?t=${encodeURIComponent(token)}&profile=${encodeURIComponent(profile)}&q=${compact ? 'low' : 'auto'}`)
      s.binaryType = 'blob'
      ws.current = s
      s.onopen = () => ((retry = 0), setConnected(true))
      s.onmessage = (m) => {
        if (typeof m.data === 'string') {
          try {
            const d = JSON.parse(m.data)
            if (d.t === 'state') setState({ browser: d.browser, me: !!d.me, asks: d.asks || [] })
            else if (d.t === 'error') setError(String(d.text || ''))
          } catch {
            /* not ours */
          }
          return
        }
        // pictures go straight to the <img> (no render per picture); the state only says there is one. Once drawn,
        // the server may send the next one.
        const blob = m.data as Blob
        const next = URL.createObjectURL(blob)
        const p = pace.current
        const now = performance.now()
        p.times = [...p.times.filter((x) => now - x < 2000), now]
        p.bytes = [...p.bytes.slice(-19), blob.size]
        if (p.inputAt) {
          p.delay = Math.round(now - p.inputAt)
          p.inputAt = 0
        }
        const done = () => {
          if (s.readyState === WebSocket.OPEN) s.send('{"t":"got"}')
          frameCb.current?.()
        }
        if (url.current) URL.revokeObjectURL(url.current)
        url.current = next
        if (img.current) {
          img.current.onload = done
          img.current.onerror = done
          img.current.src = next
        } else done()
        setFrame(true)
      }
      s.onclose = () => {
        setConnected(false)
        ws.current = null
        if (!stop) timer = setTimeout(open, Math.min(15000, 1000 * 2 ** retry++))
      }
    }
    open()
    return () => {
      stop = true
      clearTimeout(timer)
      ws.current?.close()
      ws.current = null
      if (url.current) URL.revokeObjectURL(url.current)
      url.current = null
      setFrame(false)
    }
  }, [active, compact, profile])

  const send = React.useCallback((d: Record<string, unknown>) => {
    if (ws.current?.readyState !== WebSocket.OPEN) return
    if (d.t !== 'size' && d.t !== 'quality' && !(d.t === 'mouse' && d.type === 'move')) pace.current.inputAt ||= performance.now()
    ws.current.send(JSON.stringify(d))
  }, [])
  const readPace = React.useCallback((): Pace => {
    const p = pace.current
    const now = performance.now()
    const n = p.times.filter((x) => now - x < 2000).length
    return { fps: n / 2, kb: p.bytes.length ? Math.round(p.bytes.reduce((a, b) => a + b, 0) / p.bytes.length / 1024) : 0, delay: p.delay }
  }, [])
  // the <img> of the page: shows the latest picture as soon as it is mounted
  const imgRef = React.useCallback((el: HTMLImageElement | null) => {
    img.current = el
    if (el && url.current) el.src = url.current
  }, [])
  return { frame, imgRef, state, error, setError, connected, send, readPace }
}

/** The live view of a profile. `context` = the project / topic / agent folder it is opened from (its requests first);
 *  `session` = show the tab of that session; `start` = start a stopped profile with the view; `who` = who asks (an
 *  agent's name); `onMinimize` = the window's "minimize" (hides it, the browser keeps running). */
export function LiveView({ profile, context, session, who, start, onMinimize, className }: {
  profile: string
  context?: string
  session?: string
  who?: string
  start?: boolean
  onMinimize?: () => void
  className?: string
}) {
  const t = useT()
  const scroll = React.useRef({ dx: 0, dy: 0, x: 0.5, y: 0.5, flying: false, shown: 0, raf: 0 })
  const imgEl = React.useRef<HTMLImageElement | null>(null)
  // a picture arrived: the scroll shown ahead of it is now in it; send what was scrolled since
  const onFrame = React.useCallback(() => {
    const w = scroll.current
    w.flying = false
    w.shown = 0
    if (imgEl.current) imgEl.current.style.transform = ''
    if (w.dx || w.dy) flushRef.current()
  }, [])
  const { frame, imgRef, state, error, setError, connected, send, readPace } = useLive(true, profile, onFrame)
  const flushRef = React.useRef(() => {})
  flushRef.current = () => {
    const w = scroll.current
    if (w.flying || (!w.dx && !w.dy)) return
    send({ t: 'wheel', x: w.x, y: w.y, dx: w.dx, dy: w.dy })
    w.dx = w.dy = 0
    w.flying = true
  }
  const action = useProfileAction()
  const tabOp = useBrowserTab()
  const answer = useAnswerAsk()
  const view = useBrowserProfile(profile)
  const [showPace, setShowPace] = React.useState(false)
  const [, tick] = React.useReducer((n: number) => n + 1, 0)
  React.useEffect(() => {
    if (!showPace) return
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [showPace])
  const b = state?.browser || null
  const me = !!state?.me
  const running = b?.state === 'running'
  const tabs = b?.tabs || []
  const front = tabs.find((x) => x.front)
  const shared = !!front && front.by.kind !== 'you'
  // its own requests first (the session's, then the folder's), else any
  const asks = state?.asks || []
  const ask = asks.find((a) => a.session === session) || asks.find((a) => context && a.owner.endsWith(context)) || asks[0]
  const [address, setAddress] = React.useState('')
  const [editing, setEditing] = React.useState(false)
  const [typing, setTyping] = React.useState('')
  const [note, setNote] = React.useState('')
  const pane = React.useRef<HTMLDivElement>(null)
  const lastMove = React.useRef(0)
  const started = React.useRef(false)
  const focused = React.useRef(false)

  React.useEffect(() => {
    if (!editing) setAddress(b?.page?.url && b.page.url !== 'about:blank' ? b.page.url : '')
  }, [b?.page?.url, editing])
  React.useEffect(() => {
    if (!error) return
    const id = setTimeout(() => setError(null), 6000)
    return () => clearTimeout(id)
  }, [error, setError])
  React.useEffect(() => {
    if (me) pane.current?.focus()
  }, [me])

  const startIt = () => {
    started.current = true
    action.mutate({ profile, action: 'open', ...(session ? { session } : {}) })
  }
  // "Open the browser" / a session's "Watch": a stopped browser starts with the view, on that session's tab
  React.useEffect(() => {
    if (started.current || !state) return
    if (!running && b?.state !== 'starting' && (start || session)) startIt()
  })
  React.useEffect(() => {
    if (focused.current || !running || !session) return
    focused.current = true
    const tab = tabOfSession(tabs, session, context)
    if (tab && !tab.front) tabOp.mutate({ profile, op: 'show', key: tab.key })
  }, [running, session, context, tabs, tabOp, profile])

  // the page is laid out for the size of this view, like a browser window (sent again on reconnect / start)
  React.useEffect(() => {
    const el = pane.current
    if (!el || !connected || !running) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const tell = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.height > 0) send({ t: 'size', w: Math.round(r.width), h: Math.round(r.height) })
      }, 200)
    }
    const ro = new ResizeObserver(tell)
    ro.observe(el)
    tell()
    return () => (clearTimeout(timer), ro.disconnect())
  }, [connected, running, send])

  const xy = (e: React.PointerEvent | React.WheelEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }
  }
  const mods = (e: React.KeyboardEvent | React.PointerEvent | React.WheelEvent) => ({ alt: e.altKey, ctrl: e.ctrlKey, meta: e.metaKey, shift: e.shiftKey })
  const button = (n: number) => (n === 1 ? 'middle' : n === 2 ? 'right' : 'left')

  // Handing back while Claude waits answers its request ("done"), with the person's word for it.
  const handBack = () => {
    const done = !!ask
    send({ t: 'release', done, ...(done && note.trim() ? { note: note.trim() } : {}) })
    if (done) setNote('')
  }
  // Claude is acting on the tab shown: a first click takes over instead of clicking the page
  const veil = !!frame && running && !me && (b?.busy || (!!ask && shared))
  const blank = running && !!front && !front.asleep && (front.url === 'about:blank' || front.url === '')
  const secure = (b?.page?.url || '').startsWith('https://')
  const drive = (d: Record<string, unknown>) => running && send(d)
  const mem = b?.mem || 0
  const sites = view.data?.profile.web === 'list' ? view.data.profile.sites : []
  const pace = showPace ? readPace() : null
  // the picture follows the wheel at once (clamped to a third of its height), until the real one comes
  const wheel = (e: React.WheelEvent<HTMLImageElement>) => {
    const w = scroll.current
    const p = xy(e)
    w.x = p.x
    w.y = p.y
    const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? e.currentTarget.clientHeight : 1
    w.dx += e.deltaX * k
    w.dy += e.deltaY * k
    const r = e.currentTarget.getBoundingClientRect()
    const scale = r.height / (e.currentTarget.naturalHeight || r.height)
    w.shown = Math.max(-r.height / 3, Math.min(r.height / 3, w.shown + e.deltaY * k * scale))
    e.currentTarget.style.transform = `translateY(${-w.shown}px)`
    cancelAnimationFrame(w.raf)
    w.raf = requestAnimationFrame(() => flushRef.current())
  }

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden bg-background', className)} data-testid="browser-live">
      {/* tabs + new tab + the window's minimize */}
      <div className="flex h-10 shrink-0 items-end gap-1 bg-muted/70 pr-1.5 pl-2">
        <div className="flex min-w-0 flex-1 items-end gap-0.5 overflow-x-auto" role="tablist" aria-label={t('browser.tabs')}>
          {tabs.map((tab) => (
            <TabButton key={tab.key} tab={tab} onShow={() => tabOp.mutate({ profile, op: 'show', key: tab.key })} onClose={() => tabOp.mutate({ profile, op: 'close', key: tab.key })} />
          ))}
          <Button variant="ghost" size="icon-sm" className="mb-1 shrink-0" onClick={() => tabOp.mutate({ profile, op: 'new' })} title={t('browser.newTab')} aria-label={t('browser.newTab')} data-testid="browser-new-tab">
            <Plus />
          </Button>
        </div>
        {onMinimize && (
          <Button variant="ghost" size="icon-sm" className="mb-1 shrink-0" onClick={onMinimize} title={t('browser.minimize')} aria-label={t('browser.minimize')} data-testid="browser-minimize">
            <Minus />
          </Button>
        )}
      </div>

      {/* toolbar: back, forward, reload and the address */}
      <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5">
        <Button variant="ghost" size="icon-sm" disabled={!running} onClick={() => drive({ t: 'back' })} aria-label={t('browser.back')}>
          <ArrowLeft />
        </Button>
        <Button variant="ghost" size="icon-sm" disabled={!running} onClick={() => drive({ t: 'forward' })} aria-label={t('browser.forward')}>
          <ArrowRight />
        </Button>
        <Button variant="ghost" size="icon-sm" disabled={!running} onClick={() => drive({ t: 'reload' })} aria-label={t('browser.reload')}>
          <RotateCw />
        </Button>
        <form
          className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-full bg-muted/60 px-3 focus-within:ring-2 focus-within:ring-ring"
          onSubmit={(e) => {
            e.preventDefault()
            if (address.trim()) drive({ t: 'nav', url: address.trim() })
            setEditing(false)
            ;(document.activeElement as HTMLElement | null)?.blur()
          }}
        >
          {secure ? <Lock className="size-3 shrink-0 text-muted-foreground" /> : <Globe className="size-3 shrink-0 text-muted-foreground" />}
          <input
            value={address}
            readOnly={!running}
            onFocus={() => setEditing(true)}
            onBlur={() => setEditing(false)}
            onChange={(e) => setAddress(e.target.value)}
            placeholder={running ? t('browser.addressHint') : t('browser.notRunning')}
            aria-label={t('browser.address')}
            className="h-full min-w-0 flex-1 bg-transparent font-mono text-[12px] outline-none read-only:cursor-default"
            data-testid="browser-address"
          />
        </form>
      </div>

      {/* what Claude asked, or "you have this shared tab" */}
      {(ask || (me && shared)) && (
        <div className={cn('flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2 text-[13px]', ask ? 'bg-warning/10' : 'bg-primary/8')} data-testid="browser-ask">
          <Hand className={cn('size-4 shrink-0', ask ? 'text-warning' : 'text-primary')} />
          <span className="min-w-0 flex-1">
            {ask ? (
              <>
                <span className="font-medium">{who ? t('browser.ask.whoNeeds', { name: who }) : t('browser.ask.title')}</span> {ask.reason}
              </>
            ) : (
              <span className="font-medium">{t('browser.youHaveTab')}</span>
            )}
          </span>
          {ask && !me && (
            <Button size="sm" variant="ghost" className="h-7" onClick={() => answer.mutate({ id: ask.id, action: 'skip' })} data-testid="browser-ask-skip">
              <SkipForward /> {t('browser.ask.skip')}
            </Button>
          )}
          {(me || ask) && (
            <div className="flex w-full items-center gap-2 sm:w-auto">
              {ask && (
                <Input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handBack())}
                  maxLength={500}
                  placeholder={t('browser.ask.note')}
                  aria-label={t('browser.ask.note')}
                  className="h-8 min-w-0 flex-1 bg-background text-[13px] sm:w-60"
                  data-testid="browser-ask-note"
                />
              )}
              <Button size="sm" className="h-8 shrink-0" onClick={handBack} data-testid="browser-handback">
                {t('browser.handBackToClaude')}
              </Button>
            </div>
          )}
        </div>
      )}

      {/* the page */}
      <div
        ref={pane}
        tabIndex={running ? 0 : -1}
        data-no-drag
        className={cn('group relative grid min-h-48 flex-1 items-start justify-items-center overflow-hidden bg-muted/30 outline-none', me && shared && 'ring-2 ring-primary/60 ring-inset')}
        onKeyDown={(e) => {
          if (!running || veil || e.nativeEvent.isComposing) return
          e.preventDefault()
          const text = e.key.length === 1 ? e.key : e.key === 'Enter' ? '\r' : ''
          send({ t: 'key', type: 'down', key: e.key, code: e.code, keyCode: e.keyCode, text, ...mods(e) })
        }}
        onKeyUp={(e) => {
          if (!running || veil) return
          e.preventDefault()
          send({ t: 'key', type: 'up', key: e.key, code: e.code, keyCode: e.keyCode, ...mods(e) })
        }}
      >
        {frame && running && !front?.asleep ? (
          <img
            ref={(el) => {
              imgEl.current = el
              imgRef(el)
            }}
            alt={b?.page?.title || t('browser.page')}
            draggable={false}
            className="block h-auto max-h-full w-auto max-w-full cursor-default touch-none select-none"
            onPointerDown={(e) => {
              e.preventDefault()
              pane.current?.focus()
              ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
              send({ t: 'mouse', type: 'down', ...xy(e), button: button(e.button), clicks: e.detail || 1, ...mods(e) })
            }}
            onPointerUp={(e) => send({ t: 'mouse', type: 'up', ...xy(e), button: button(e.button), clicks: e.detail || 1, ...mods(e) })}
            onPointerMove={(e) => {
              const now = performance.now()
              if (now - lastMove.current < 40) return
              lastMove.current = now
              send({ t: 'mouse', type: 'move', ...xy(e), ...mods(e) })
            }}
            onWheel={wheel}
            onContextMenu={(e) => e.preventDefault()}
          />
        ) : (
          <div className="grid place-items-center self-center p-6 text-center text-[13px] text-muted-foreground">
            {b?.state === 'starting' || action.isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> {t('browser.starting')}
              </span>
            ) : running ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> {t('browser.loading')}
              </span>
            ) : (
              <div className="grid justify-items-center gap-2">
                <Globe className="size-6 opacity-60" />
                <span>{connected ? t('browser.idle') : t('browser.connecting')}</span>
                <Button size="sm" variant="outline" onClick={startIt} data-testid="browser-open">
                  {t('browser.open')}
                </Button>
              </div>
            )}
          </div>
        )}

        {/* a new tab: the sites of the list, and what this browser is for */}
        {blank && !veil && (
          <div className="absolute inset-0 grid place-items-center overflow-auto bg-background p-6" data-testid="browser-ntp">
            <div className="grid w-full max-w-lg justify-items-center gap-4 text-center">
              <div className="grid gap-1">
                <p className="text-base font-semibold">{t('browser.name')}</p>
                <p className="text-[13px] text-muted-foreground">{t('browser.ntp.desc')}</p>
              </div>
              {sites.length > 0 && (
                <div className="flex flex-wrap justify-center gap-2">
                  {sites.slice(0, 12).map((site) => (
                    <button key={site} type="button" onClick={() => drive({ t: 'nav', url: `https://${site}/` })} className="inline-flex h-9 items-center gap-1.5 rounded-lg border bg-card px-3 text-[13px] hover:bg-accent">
                      <Globe className="size-3.5 text-muted-foreground" /> {site}
                    </button>
                  ))}
                </div>
              )}
              <p className="text-[12px] text-muted-foreground">{t('browser.ntp.type')}</p>
            </div>
          </div>
        )}

        {/* Claude is using this tab: the first click takes over */}
        {veil && (
          <button
            type="button"
            onClick={() => send({ t: 'take' })}
            className={cn(
              'absolute inset-0 grid cursor-pointer place-items-center bg-background/60 transition-opacity focus-visible:outline-none',
              ask ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100 pointer-coarse:bg-transparent',
            )}
            data-testid="browser-take"
          >
            <span className={cn('inline-flex items-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground shadow-pop', !ask && 'pointer-coarse:hidden')}>
              <MousePointerClick className="size-4" /> {t('browser.clickToTake')}
            </span>
          </button>
        )}
        {frame && running && !me && b?.busy && !ask && (
          <span className="pointer-events-none absolute top-2 left-2 inline-flex items-center gap-1.5 rounded-full bg-background/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-xs">
            <span className="size-1.5 animate-pulse rounded-full bg-primary" /> {t('browser.claudeDriving')}
          </span>
        )}
      </div>

      {/* typing on a phone (no physical keyboard on the picture) */}
      {running && (
        <form
          className="flex shrink-0 gap-1 border-t p-1.5 md:hidden"
          onSubmit={(e) => {
            e.preventDefault()
            if (typing) send({ t: 'text', text: typing })
            setTyping('')
          }}
        >
          <Input value={typing} onChange={(e) => setTyping(e.target.value)} placeholder={t('browser.typeHere')} aria-label={t('browser.typeHere')} className="h-8 flex-1 text-[13px]" />
          <Button size="sm" variant="outline" className="h-8" type="submit" aria-label={t('browser.typeSend')}>
            <Keyboard />
          </Button>
          <Button size="sm" variant="outline" className="h-8" type="button" onClick={() => send({ t: 'key', type: 'down', key: 'Enter', code: 'Enter', keyCode: 13, text: '\r' })}>
            ↵
          </Button>
        </form>
      )}

      {/* status bar: memory, what was refused, Stop */}
      <div className="flex h-7 shrink-0 items-center gap-3 border-t bg-muted/40 px-3 text-[11px] text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">
          {error ? (
            <span className="text-warning">{error}</span>
          ) : pace ? (
            <span className="font-mono" data-testid="browser-pace">
              {t('browser.pace', { fps: pace.fps.toFixed(1), kb: pace.kb })}
              {pace.delay != null ? ` · ${t('browser.paceDelay', { ms: pace.delay })}` : ''}
            </span>
          ) : running && b?.blocked?.length ? (
            <span title={b.blocked.join(', ')}>{t('browser.blocked', { count: b.blocked.length })}</span>
          ) : null}
        </span>
        {running && (
          <button type="button" className={cn('inline-flex shrink-0 items-center gap-1 hover:text-foreground', showPace && 'text-foreground')} onClick={() => setShowPace((v) => !v)} title={t('browser.paceTitle')} aria-pressed={showPace} data-testid="browser-pace-toggle">
            <Gauge className="size-3" />
          </button>
        )}
        {running && (
          <span className="inline-flex shrink-0 items-center gap-1" title={t('browser.memTitle')} data-testid="browser-mem">
            {mem ? `${fmtBytes(mem)} · ` : ''}
            {t('browser.tabsAwake', { count: tabs.filter((x) => !x.asleep).length })}
          </span>
        )}
        {running && tabs.filter((x) => !x.asleep).length > 1 && (
          <button type="button" className="inline-flex shrink-0 items-center gap-1 hover:text-foreground" onClick={() => action.mutate({ profile, action: 'sleep' })} data-testid="browser-sleep">
            <Moon className="size-3" /> {t('browser.sleepTabs')}
          </button>
        )}
        {running && (
          <button type="button" className="inline-flex shrink-0 items-center gap-1 hover:text-foreground" onClick={() => action.mutate({ profile, action: 'stop' })} data-testid="browser-stop">
            <Square className="size-3" /> {t('browser.stop')}
          </button>
        )}
      </div>
    </div>
  )
}

/** One tab: its title, asleep or not, a dot when Claude (a session or an agent) opened it. */
function TabButton({ tab, onShow, onClose }: { tab: BrowserTab; onShow: () => void; onClose: () => void }) {
  const t = useT()
  const label = tab.title || (tab.url && tab.url !== 'about:blank' ? tab.url : t('browser.newTab'))
  const by = tab.by.kind === 'agent' ? t('browser.by.agent', { name: tab.by.name || '' }) : tab.by.kind === 'session' ? t('browser.by.session') : t('browser.by.you')
  return (
    <div
      role="tab"
      aria-selected={tab.front}
      className={cn(
        'group/tab flex h-8 max-w-60 min-w-0 shrink-0 items-center gap-1 rounded-t-lg pr-1 pl-2.5 text-xs',
        tab.front ? 'bg-background text-foreground' : 'text-muted-foreground hover:bg-background/50',
        tab.asleep && 'italic opacity-70',
      )}
      title={`${tab.url}\n${by}${tab.asleep ? `\n${t('browser.asleep')}` : ''}`}
      data-testid="browser-tab"
      data-by={tab.by.kind}
    >
      <button type="button" onClick={onShow} className="flex min-w-0 flex-1 items-center gap-1.5 text-left">
        {tab.asleep ? <Moon className="size-3.5 shrink-0 opacity-70" /> : tab.by.kind !== 'you' ? <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-hidden /> : null}
        <span className="truncate">{label}</span>
      </button>
      <button type="button" onClick={onClose} className="inline-flex size-5 shrink-0 items-center justify-center rounded opacity-60 hover:bg-muted hover:opacity-100" aria-label={t('browser.closeTab')} data-testid="browser-tab-close">
        <X className="size-3" />
      </button>
    </div>
  )
}
