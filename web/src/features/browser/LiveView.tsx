// The live view of the Harness Browser (WS /api/browser/live), drawn as a browser window: its tabs (each with who sees
// it: only me, a topic, a project), a toolbar with the address, the page as pictures (JPEG frames) and a status bar
// (memory, Stop). The person drives the tab shown as soon as they click or type; on a tab Claude is using right now,
// a first click takes over (Claude's commands on that tab then wait). What Claude asked shows as an info bar with
// "Hand back to Claude". Coordinates are sent as 0..1 of the picture: the server maps them to the page's size.
import * as React from 'react'
import {
  ArrowLeft, ArrowRight, Check, ChevronDown, Globe, Hand, Keyboard, Loader2, Lock, Minus, Moon, MousePointerClick,
  Plus, RotateCw, SkipForward, Square, TriangleAlert, X,
} from 'lucide-react'
import { useT } from '@/i18n'
import { browserLiveToken, useAnswerAsk, useBrowserAction, useBrowserStatus, useBrowserTab, useWorkspace } from '@/lib/queries'
import type { BrowserAsk, BrowserState, BrowserTab } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { useCompact } from '@/stores/media'
import { cn } from '@/lib/utils'
import {
  Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Input,
} from '@/components/ui'
import { ME, ScopeIcon, agentScope, projectScope, scopeKind, scopeName, scopeTopic, tabOfSession, topicScope } from './scope'

type LiveState = { browser: BrowserState | null; me: boolean; asks: BrowserAsk[] }

/** The WebSocket of the live view: pictures + state; reconnects while mounted. */
function useLive(active: boolean) {
  const compact = useCompact()
  const [frame, setFrame] = React.useState(false)
  const img = React.useRef<HTMLImageElement | null>(null)
  const [state, setState] = React.useState<LiveState | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [connected, setConnected] = React.useState(false)
  const ws = React.useRef<WebSocket | null>(null)
  const url = React.useRef<string | null>(null)

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
      const s = new WebSocket(`${proto}://${location.host}/api/browser/live?t=${encodeURIComponent(token)}&q=${compact ? 'low' : 'high'}`)
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
        // pictures go straight to the <img> (no render per picture); the state only says there is one
        const next = URL.createObjectURL(m.data as Blob)
        if (url.current) URL.revokeObjectURL(url.current)
        url.current = next
        if (img.current) img.current.src = next
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
  }, [active, compact])

  const send = React.useCallback((d: Record<string, unknown>) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(d))
  }, [])
  // the <img> of the page: shows the latest picture as soon as it is mounted
  const imgRef = React.useCallback((el: HTMLImageElement | null) => {
    img.current = el
    if (el && url.current) el.src = url.current
  }, [])
  return { frame, imgRef, state, error, setError, connected, send }
}

/** The live view. `context` = the topic / agent folder it is opened from (its share shortcuts, its requests first);
 *  `session` = show the tab of that session; `start` = start a stopped browser with the view; `who` = who asks (an
 *  agent's name); `onMinimize` = the window's "minimize" (hides it, the browser keeps running). */
export function LiveView({ context, session, who, start, onMinimize, className }: {
  context?: string
  session?: string
  who?: string
  start?: boolean
  onMinimize?: () => void
  className?: string
}) {
  const t = useT()
  const { frame, imgRef, state, error, setError, connected, send } = useLive(true)
  const action = useBrowserAction()
  const tabOp = useBrowserTab()
  const answer = useAnswerAsk()
  const status = useBrowserStatus()
  const b = state?.browser || null
  const me = !!state?.me
  const running = b?.state === 'running'
  const tabs = b?.tabs || []
  const front = tabs.find((x) => x.front)
  const shared = !!front && front.scope !== ME
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
    action.mutate({ action: 'open', ...(session ? { session } : {}) })
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
    if (tab && !tab.front) tabOp.mutate({ op: 'show', key: tab.key })
  }, [running, session, context, tabs, tabOp])

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
  const mem = b?.mem

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden bg-background', className)} data-testid="browser-live">
      {/* tabs + new tab + the window's minimize */}
      <div className="flex h-10 shrink-0 items-end gap-1 bg-muted/70 pr-1.5 pl-2">
        <div className="flex min-w-0 flex-1 items-end gap-0.5 overflow-x-auto" role="tablist" aria-label={t('browser.tabs')}>
          {tabs.map((tab) => (
            <TabButton key={tab.key} tab={tab} context={context} onShow={() => tabOp.mutate({ op: 'show', key: tab.key })} onClose={() => tabOp.mutate({ op: 'close', key: tab.key })} onScope={(scope) => tabOp.mutate({ op: 'scope', key: tab.key, scope })} />
          ))}
          <Button variant="ghost" size="icon-sm" className="mb-1 shrink-0" onClick={() => tabOp.mutate({ op: 'new' })} title={t('browser.newTab')} aria-label={t('browser.newTab')} data-testid="browser-new-tab">
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
            ref={imgRef}
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
            onWheel={(e) => send({ t: 'wheel', ...xy(e), dx: e.deltaX, dy: e.deltaY })}
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
              {(status.data?.settings.web === 'list' ? status.data.settings.sites : []).length > 0 && (
                <div className="flex flex-wrap justify-center gap-2">
                  {status.data!.settings.sites.slice(0, 12).map((site) => (
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
              'absolute inset-0 grid cursor-pointer place-items-center bg-background/40 backdrop-blur-[1px] transition-opacity focus-visible:outline-none',
              ask ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100 pointer-coarse:bg-transparent pointer-coarse:backdrop-blur-none',
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
          ) : running && b?.blocked?.length ? (
            <span title={b.blocked.join(', ')}>{t('browser.blocked', { count: b.blocked.length })}</span>
          ) : null}
        </span>
        {running && mem && (
          <span className={cn('inline-flex shrink-0 items-center gap-1', mem.level !== 'ok' && 'text-warning')} title={t('browser.memTitle')} data-testid="browser-mem">
            {mem.level !== 'ok' && <TriangleAlert className="size-3" />}
            {mem.browser ? `${fmtBytes(mem.browser)} · ` : ''}
            {t('browser.tabsAwake', { count: tabs.filter((x) => !x.asleep).length })}
          </span>
        )}
        {running && tabs.filter((x) => !x.asleep).length > 1 && (
          <button type="button" className="inline-flex shrink-0 items-center gap-1 hover:text-foreground" onClick={() => action.mutate({ action: 'sleep' })} data-testid="browser-sleep">
            <Moon className="size-3" /> {t('browser.sleepTabs')}
          </button>
        )}
        {running && (
          <button type="button" className="inline-flex shrink-0 items-center gap-1 hover:text-foreground" onClick={() => action.mutate({ action: 'stop' })} data-testid="browser-stop">
            <Square className="size-3" /> {t('browser.stop')}
          </button>
        )}
      </div>
    </div>
  )
}

/** One tab: its scope (lock / topic / project), its title, asleep or not; the shown one has a menu "Share with". */
function TabButton({ tab, context, onShow, onClose, onScope }: {
  tab: BrowserTab
  context?: string
  onShow: () => void
  onClose: () => void
  onScope: (scope: string) => void
}) {
  const t = useT()
  const Icon = ScopeIcon(tab.scope)
  const label = tab.title || (tab.url && tab.url !== 'about:blank' ? tab.url : t('browser.newTab'))
  const by = tab.by.kind === 'agent' ? t('browser.by.agent', { name: tab.by.name || '' }) : tab.by.kind === 'session' ? t('browser.by.session') : t('browser.by.you')
  const where = scopeKind(tab.scope) === 'me' ? t('browser.scope.me') : t(`browser.scope.${scopeKind(tab.scope)}`, { name: scopeName(tab.scope), topic: scopeTopic(tab.scope) })
  return (
    <div
      role="tab"
      aria-selected={tab.front}
      className={cn(
        'group/tab flex h-8 max-w-60 min-w-0 shrink-0 items-center gap-1 rounded-t-lg pr-1 pl-2.5 text-xs',
        tab.front ? 'bg-background text-foreground' : 'text-muted-foreground hover:bg-background/50',
        tab.asleep && 'italic opacity-70',
      )}
      title={`${tab.url}\n${where} · ${by}${tab.asleep ? `\n${t('browser.asleep')}` : ''}`}
      data-testid="browser-tab"
      data-scope={tab.scope}
    >
      <button type="button" onClick={onShow} className="flex min-w-0 flex-1 items-center gap-1.5 text-left">
        {tab.asleep ? <Moon className="size-3.5 shrink-0 opacity-70" /> : tab.by.kind !== 'you' ? <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-hidden /> : null}
        <span className="truncate">{label}</span>
      </button>
      <ShareMenu tab={tab} context={context} onScope={onScope}>
        <button type="button" className={cn('inline-flex h-5 shrink-0 items-center gap-0.5 rounded px-1 text-[10px] hover:bg-muted', tab.scope !== ME && 'bg-primary/10 text-primary')} aria-label={t('browser.share')} data-testid="browser-tab-share">
          <Icon className="size-3" />
          {tab.scope !== ME && <span className="max-w-24 truncate not-italic">{scopeName(tab.scope)}</span>}
          <ChevronDown className="size-2.5 opacity-60" />
        </button>
      </ShareMenu>
      <button type="button" onClick={onClose} className="inline-flex size-5 shrink-0 items-center justify-center rounded opacity-60 hover:bg-muted hover:opacity-100" aria-label={t('browser.closeTab')} data-testid="browser-tab-close">
        <X className="size-3" />
      </button>
    </div>
  )
}

/** "Share with": only me, the topic / project / agent it was opened from (and that topic's agents), then every project,
 *  topic and agent. An agent only sees the tabs shared with it, never the topic's. */
function ShareMenu({ tab, context, onScope, children }: { tab: BrowserTab; context?: string; onScope: (scope: string) => void; children: React.ReactNode }) {
  const t = useT()
  const ws = useWorkspace()
  const item = (scope: string, label: string) => (
    <DropdownMenuItem key={scope} onSelect={() => onScope(scope)} data-testid={`browser-scope-${scopeKind(scope)}`}>
      <span className="flex size-4 items-center justify-center">{tab.scope === scope && <Check className="size-3.5" />}</span>
      <span className="min-w-0 truncate">{label}</span>
    </DropdownMenuItem>
  )
  const topics = (ws.data?.projects || []).flatMap((p) => p.topics)
  const agentsOf = (scope: string) => (topics.find((x) => `topic:${x.path}` === scope)?.agents || []).map((a) => `agent:${a.path}`)
  const here = context ? topicScope(context) : ME
  const near = context ? [...new Set([agentScope(context), here, projectScope(context), ...agentsOf(here)])].filter((s) => s !== ME) : []
  const others = (ws.data?.projects || [])
    .flatMap((p) => [`project:${p.path}`, ...p.topics.flatMap((x) => [`topic:${x.path}`, ...agentsOf(`topic:${x.path}`)])])
    .filter((s) => !near.includes(s))
  const name = (s: string) => t(`browser.scope.${scopeKind(s)}`, { name: scopeName(s), topic: scopeTopic(s) })
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-64 overflow-y-auto">
        <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">{t('browser.shareHint')}</DropdownMenuLabel>
        {item(ME, t('browser.scope.me'))}
        {near.length > 0 && <DropdownMenuSeparator />}
        {near.map((s) => item(s, name(s)))}
        {others.length > 0 && <DropdownMenuSeparator />}
        {others.map((s) => item(s, name(s)))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
