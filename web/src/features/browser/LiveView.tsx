// The live view of one navigator of the Harness Browser (WS /api/browser/live?profile=&nav=: a window of tabs in a
// profile's Chromium, the person's, an agent's or a session's), drawn as a browser window: its tabs (a dot on the
// ones Claude opened), a toolbar with the address, the page as pictures (JPEG frames) and a status
// bar (memory, Stop). The person drives the tab shown as soon as they click or type; on a tab Claude is using right
// now, a first click takes over (Claude's commands on that tab then wait). What Claude asked shows as an info bar with
// "Hand back to Claude". Coordinates are sent as 0..1 of the picture: the server maps them to the page's size.
// Pace: each picture is confirmed ({"t":"got"}) as soon as it arrives; the server keeps a few on their way, so a far
// connection still gets several per round trip, and a slow one fewer, never late ones. Here only the newest picture
// waiting for the <img> is drawn (one decoded at a time). The wheel is summed and sent at most once per picture; the picture moves
// at once by what was scrolled (the real one follows).
import * as React from 'react'
import {
  ArrowLeft, ArrowRight, Gauge, Globe, Hand, Keyboard, Loader2, Lock, MessageSquareWarning, Minus, Moon, MousePointerClick,
  Paperclip, Plus, RotateCw, Search, SkipForward, Square, X,
} from 'lucide-react'
import { useT } from '@/i18n'
import { browserLiveToken, giveBrowserFiles, useAnswerAsk, useBrowserProfile, useBrowserTab, useProfileAction } from '@/lib/queries'
import type { BrowserAsk, BrowserState, BrowserTab } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { useCompact } from '@/stores/media'
import { cn } from '@/lib/utils'
import { Button, Input } from '@/components/ui'
import { AsleepScene } from './AsleepScene'
import { DomainBar } from './DomainBar'
import { QuickMenu, type Quality } from './QuickMenu'

const QUALITY_KEY = 'mx.browser.quality'

type LiveState = { browser: BrowserState | null; me: boolean; asks: BrowserAsk[] }
/** What the pictures cost, measured here (the "speed" button of the status bar). */
type Pace = { fps: number; kb: number; delay: number | null }

/** The WebSocket of the live view: pictures + state; reconnects while mounted. */
function useLive(active: boolean, profile: string, nav: string, quality: Quality, onFrame?: () => void) {
  const q = React.useRef(quality)
  q.current = quality
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
  const drawing = React.useRef(false)
  const waiting = React.useRef<string | null>(null)
  const draw = React.useCallback((next: string) => {
    if (url.current) URL.revokeObjectURL(url.current)
    url.current = next
    const done = () => {
      drawing.current = false
      frameCb.current?.()
      const more = waiting.current
      waiting.current = null
      if (more) draw(more)
    }
    if (img.current) {
      drawing.current = true
      img.current.onload = done
      img.current.onerror = done
      img.current.src = next
    } else frameCb.current?.()
    setFrame(true)
  }, [])

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
      const s = new WebSocket(`${proto}://${location.host}/api/browser/live?t=${encodeURIComponent(token)}&profile=${encodeURIComponent(profile)}&nav=${encodeURIComponent(nav)}&q=${q.current}`)
      s.binaryType = 'blob'
      ws.current = s
      s.onopen = () => ((retry = 0), setConnected(true))
      s.onmessage = (m) => {
        if (typeof m.data === 'string') {
          try {
            const d = JSON.parse(m.data)
            if (d.t === 'state') setState({ browser: d.browser, me: !!d.me, asks: d.asks || [] })
            else if (d.t === 'error') setError(String(d.text || ''))
            // the text selected on the page (Ctrl/⌘+C on the picture): into the person's clipboard
            else if (d.t === 'copied' && d.text) navigator.clipboard?.writeText(String(d.text)).catch(() => {})
          } catch {
            /* not ours */
          }
          return
        }
        // pictures go straight to the <img> (no render per picture); the state only says there is one. Confirmed at
        // once (the server measures the network with it); drawn one at a time, the newest first.
        const blob = m.data as Blob
        if (s.readyState === WebSocket.OPEN) s.send('{"t":"got"}')
        const next = URL.createObjectURL(blob)
        const p = pace.current
        const now = performance.now()
        p.times = [...p.times.filter((x) => now - x < 2000), now]
        p.bytes = [...p.bytes.slice(-19), blob.size]
        if (p.inputAt) {
          p.delay = Math.round(now - p.inputAt)
          p.inputAt = 0
        }
        if (drawing.current) {
          // the <img> is still decoding the previous one: this one waits, replacing any older one waiting
          if (waiting.current) URL.revokeObjectURL(waiting.current)
          waiting.current = next
          return
        }
        draw(next)
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
      if (waiting.current) URL.revokeObjectURL(waiting.current)
      url.current = waiting.current = null
      drawing.current = false
      setFrame(false)
    }
  }, [active, profile, nav, draw])

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
    drawing.current = false             // a new <img>: nothing of the old one's is pending any more
    if (el && url.current) el.src = url.current
  }, [])
  return { frame, imgRef, state, error, setError, connected, send, readPace }
}

/** The live view of a navigator (`nav`: me, agent:<path>, session:<sid>) in the Chromium of `profile`. `session`
 *  = its requests first; `start` = start a stopped profile with the view; `who` = who asks (an agent's name);
 *  `onMinimize` = the window's "minimize" (hides it, the browser keeps running). */
export function LiveView({ profile, nav, session, who, start, onMinimize, className }: {
  profile: string
  nav: string
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
  const compact = useCompact()
  // the picture: auto (adapts to the network), smooth (lighter) or sharp; kept in this browser
  const [quality, setQuality] = React.useState<Quality>(() => {
    const v = localStorage.getItem(QUALITY_KEY)
    return v === 'auto' || v === 'low' || v === 'high' ? v : compact ? 'low' : 'auto'
  })
  const { frame, imgRef, state, error, setError, connected, send, readPace } = useLive(true, profile, nav, quality, onFrame)
  const changeQuality = (v: Quality) => {
    setQuality(v)
    localStorage.setItem(QUALITY_KEY, v)
    send({ t: 'quality', q: v })
  }
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
  // a closed tab leaves the row at once; it comes back only if the browser still has it after a while (refused: at once)
  const [closing, setClosing] = React.useState<Record<string, number>>({})
  const all = b?.tabs || []
  const tabs = all.filter((x) => !closing[x.key] || Date.now() - closing[x.key] > 8000)
  React.useEffect(() => {
    const keys = Object.keys(closing)
    if (!keys.length) return
    const left = keys.filter((k) => all.some((x) => x.key === k) && Date.now() - closing[k] <= 8000)
    if (left.length !== keys.length) setClosing(Object.fromEntries(left.map((k) => [k, closing[k]])))
    if (!left.length) return
    const id = setTimeout(() => setClosing((c) => ({ ...c })), 8100)
    return () => clearTimeout(id)
  }, [all, closing])
  const closeTab = (key: string) => {
    setClosing((c) => ({ ...c, [key]: Date.now() }))
    tabOp.mutate({ profile, op: 'close', key }, {
      onError: () => setClosing((c) => Object.fromEntries(Object.entries(c).filter(([k]) => k !== key))),
    })
  }
  const front = tabs.find((x) => x.front)
  const shared = !!front && front.by.kind !== 'you'
  // the requests of this navigator's turns (the session's first)
  const asks = state?.asks || []
  const ask = asks.find((a) => a.session === session) || asks[0]
  const [address, setAddress] = React.useState('')
  const [editing, setEditing] = React.useState(false)
  const [typing, setTyping] = React.useState('')
  const [note, setNote] = React.useState('')
  const [search, setSearch] = React.useState('')
  const [prompt, setPrompt] = React.useState('')
  const [sending, setSending] = React.useState(false)
  const filePick = React.useRef<HTMLInputElement>(null)
  const pane = React.useRef<HTMLDivElement>(null)
  const lastMove = React.useRef(0)
  const started = React.useRef(false)

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
    action.mutate({ profile, action: 'open', nav })
  }
  // "Open the browser" / a session's "Watch": a stopped browser starts with the view. A running one whose tabs of
  // this navigator all sleep wakes its last one (the person came to look at it).
  const awake = tabs.filter((x) => !x.asleep).length
  React.useEffect(() => {
    if (started.current || !state || b?.state === 'starting') return
    if ((!running && start) || (running && !awake && tabs.length > 0)) startIt()
  })

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

  const xy = (e: React.PointerEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }
  }
  const mods = (e: React.KeyboardEvent | React.PointerEvent) => ({ alt: e.altKey, ctrl: e.ctrlKey, meta: e.metaKey, shift: e.shiftKey })
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
  const pace = showPace ? readPace() : null
  // the picture follows the wheel at once (clamped to a third of its height), until the real one comes
  // Listened to natively (React's wheel is passive): the wheel scrolls the page in the browser, never Harness around it.
  const wheelRef = React.useRef((_e: WheelEvent) => {})
  wheelRef.current = (e: WheelEvent) => {
    const img = imgEl.current
    if (!img || e.target !== img || !running || veil) return
    e.preventDefault()
    const w = scroll.current
    const r = img.getBoundingClientRect()
    w.x = (e.clientX - r.left) / r.width
    w.y = (e.clientY - r.top) / r.height
    const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? img.clientHeight : 1
    w.dx += e.deltaX * k
    w.dy += e.deltaY * k
    const scale = r.height / (img.naturalHeight || r.height)
    w.shown = Math.max(-r.height / 3, Math.min(r.height / 3, w.shown + e.deltaY * k * scale))
    img.style.transform = `translateY(${-w.shown}px)`
    cancelAnimationFrame(w.raf)
    w.raf = requestAnimationFrame(() => flushRef.current())
  }
  React.useEffect(() => {
    const el = pane.current
    if (!el) return
    const on = (e: WheelEvent) => wheelRef.current(e)
    el.addEventListener('wheel', on, { passive: false })
    return () => el.removeEventListener('wheel', on)
  }, [])

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden bg-background', className)} data-testid="browser-live">
      {/* tabs + new tab + the window's minimize */}
      <div className="flex h-10 shrink-0 items-end gap-1 bg-muted pr-1.5 pl-2">
        <div className="flex min-w-0 flex-1 items-end gap-0.5 overflow-x-auto" role="tablist" aria-label={t('browser.tabs')}>
          {tabs.map((tab) => (
            <TabButton key={tab.key} tab={tab} onShow={() => tabOp.mutate({ profile, op: 'show', key: tab.key })} onClose={() => closeTab(tab.key)} />
          ))}
          <Button variant="ghost" size="icon-sm" className="mb-1 shrink-0" onClick={() => tabOp.mutate({ profile, op: 'new', nav })} title={t('browser.newTab')} aria-label={t('browser.newTab')} data-testid="browser-new-tab">
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
          className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-full bg-muted px-3 focus-within:ring-2 focus-within:ring-ring"
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
        <QuickMenu profile={profile} nav={nav} quality={quality} onQuality={changeQuality} />
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

      {/* a sandboxed agent's browser on a site outside its domains: add it, or its next step empties the tab */}
      {b?.page?.url && <DomainBar nav={nav} url={b.page.url} who={who} />}

      {/* the page */}
      <div
        ref={pane}
        tabIndex={running ? 0 : -1}
        data-no-drag
        className={cn('group relative grid min-h-48 flex-1 items-start justify-items-center overflow-hidden bg-fill-1 outline-none', me && shared && 'ring-2 ring-primary/60 ring-inset')}
        onKeyDown={(e) => {
          if (!running || veil || e.nativeEvent.isComposing) return
          const cmd = e.ctrlKey || e.metaKey
          // paste: let the browser give us the clipboard (onPaste), the page gets it as typed text
          if (cmd && !e.altKey && e.key.toLowerCase() === 'v') return
          if (cmd && !e.altKey && ['c', 'x'].includes(e.key.toLowerCase())) send({ t: 'copy' })
          e.preventDefault()
          const text = e.key.length === 1 ? e.key : e.key === 'Enter' ? '\r' : ''
          send({ t: 'key', type: 'down', key: e.key, code: e.code, keyCode: e.keyCode, text, ...mods(e) })
        }}
        onPaste={(e) => {
          if (!running || veil) return
          const text = e.clipboardData.getData('text/plain')
          e.preventDefault()
          if (text) send({ t: 'text', text: text.slice(0, 2000) })
        }}
        onKeyUp={(e) => {
          if (!running || veil) return
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') return
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
            onContextMenu={(e) => e.preventDefault()}
          />
        ) : connected && b?.state !== 'starting' && !action.isPending && !(running && awake > 0) ? (
          <AsleepScene project={view.data?.profile.project || ''} label={t('browser.idle')} size="lg">
            <Button size="sm" variant="secondary" className="shadow-md" onClick={startIt} data-testid="browser-open">
              {t('browser.open')}
            </Button>
          </AsleepScene>
        ) : (
          <div className="grid place-items-center self-center p-6 text-center text-[13px] text-muted-foreground">
            {b?.state === 'starting' || action.isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> {t('browser.starting')}
              </span>
            ) : running && awake > 0 ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" /> {t('browser.loading')}
              </span>
            ) : (
              <div className="grid justify-items-center gap-2">
                <Globe className="size-6 opacity-60" />
                <span>{t('browser.connecting')}</span>
              </div>
            )}
          </div>
        )}

        {/* a new tab: what this browser is for, and the address bar */}
        {blank && !veil && (
          <div className="absolute inset-0 grid place-items-center overflow-auto bg-background p-6" data-testid="browser-ntp">
            <div className="grid w-full max-w-lg justify-items-center gap-4 text-center">
              <div className="grid gap-1">
                <p className="text-base font-semibold">{t('browser.name')}</p>
                <p className="text-[13px] text-muted-foreground">{t('browser.ntp.desc')}</p>
              </div>
              <form
                className="flex h-10 w-full max-w-md items-center gap-2 rounded-full border bg-card px-4 focus-within:ring-2 focus-within:ring-ring"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (search.trim()) drive({ t: 'nav', url: search.trim() })
                  setSearch('')
                }}
              >
                <Search className="size-4 shrink-0 text-muted-foreground" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('browser.addressHint')} aria-label={t('browser.addressHint')} className="h-full min-w-0 flex-1 bg-transparent text-[14px] outline-none" data-testid="browser-ntp-search" />
              </form>
            </div>
          </div>
        )}

        {/* the page opened an alert / confirm / prompt: the person answers it here */}
        {running && b?.dialog && (
          <div className="absolute inset-0 z-10 grid place-items-start justify-items-center bg-background/40 pt-10" data-testid="browser-dialog">
            <form
              className="grid w-[min(28rem,calc(100%-2rem))] gap-3 rounded-xl border bg-popover p-4 text-[13px] shadow-pop"
              onSubmit={(e) => {
                e.preventDefault()
                send({ t: 'dialog', accept: true, text: prompt })
                setPrompt('')
              }}
            >
              <div className="flex items-start gap-2">
                <MessageSquareWarning className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="grid min-w-0 gap-1">
                  <p className="font-medium">{t(b.dialog.type === 'beforeunload' ? 'browser.dialog.leave' : 'browser.dialog.title')}</p>
                  {b.dialog.message && <p className="whitespace-pre-wrap break-words text-muted-foreground">{b.dialog.message}</p>}
                </div>
              </div>
              {b.dialog.type === 'prompt' && (
                <Input autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={b.dialog.default} className="h-8 text-[13px]" data-testid="browser-dialog-text" />
              )}
              <div className="flex justify-end gap-2">
                {b.dialog.type !== 'alert' && (
                  <Button size="sm" type="button" variant="outline" onClick={() => send({ t: 'dialog', accept: false })} data-testid="browser-dialog-cancel">
                    {t('common.cancel')}
                  </Button>
                )}
                <Button size="sm" type="submit" autoFocus={b.dialog.type !== 'prompt'} data-testid="browser-dialog-ok">
                  {b.dialog.type === 'beforeunload' ? t('browser.dialog.leaveOk') : t('common.ok')}
                </Button>
              </div>
            </form>
          </div>
        )}
        {/* a file input was clicked: the person picks the files on their device */}
        {running && b?.chooser && !b?.dialog && (
          <div className="absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-2 border-b bg-popover px-3 py-2 text-[13px] shadow-xs" data-testid="browser-chooser">
            <Paperclip className="size-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1">{t(b.chooser.multiple ? 'browser.chooser.many' : 'browser.chooser.one')}</span>
            <input
              ref={filePick}
              type="file"
              multiple={b.chooser.multiple}
              className="hidden"
              onChange={async (e) => {
                const files = Array.from(e.target.files || [])
                e.target.value = ''
                if (!files.length) return
                setSending(true)
                try {
                  await giveBrowserFiles(profile, nav, files)
                } catch (err) {
                  setError((err as Error).message || t('browser.chooser.failed'))
                } finally {
                  setSending(false)
                }
              }}
            />
            <Button size="sm" className="h-7" disabled={sending} onClick={() => filePick.current?.click()} data-testid="browser-chooser-pick">
              {sending ? <Loader2 className="animate-spin" /> : <Paperclip />} {t('browser.chooser.pick')}
            </Button>
            <Button size="sm" variant="ghost" className="h-7" onClick={() => send({ t: 'chooser' })}>
              {t('common.cancel')}
            </Button>
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
      <div className="flex h-7 shrink-0 items-center gap-3 border-t bg-fill-1 px-3 text-[11px] text-muted-foreground">
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
  const el = React.useRef<HTMLDivElement>(null)
  // the tab shown stays in sight (a new one is added at the end of a long row)
  const front = tab.front
  React.useEffect(() => {
    // only the row of tabs moves (scrollIntoView would scroll every box around it, Harness too)
    const row = el.current?.parentElement
    if (!el.current || !row || !front) return
    const me = el.current.getBoundingClientRect()
    const box = row.getBoundingClientRect()
    if (me.left < box.left) row.scrollLeft -= box.left - me.left
    else if (me.right > box.right) row.scrollLeft += me.right - box.right
  }, [front])
  const label = tab.title || (tab.url && tab.url !== 'about:blank' ? tab.url : t('browser.newTab'))
  const by = tab.by.kind === 'agent' ? t('browser.by.agent', { name: tab.by.name || '' }) : tab.by.kind === 'session' ? t('browser.by.session') : t('browser.by.you')
  return (
    <div
      ref={el}
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
