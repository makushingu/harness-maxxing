// The terminal drawer under a session's conversation (Ctrl+J, /terminal, the session's options): one tab per terminal,
// each opened in a repository of the session (or its topic folder), "Send the selection to Claude" quotes it in the
// composer. Loaded on first use (xterm.js). A page reload finds the terminals again (the server replays their output).
import * as React from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, MessageSquareQuote, Plus, SquareTerminal, X } from 'lucide-react'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Sensitive, Tooltip, toast } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useIsMobile } from '@/stores/media'
import { termApi, termKey, termSocketUrl, useTermState } from './api'
import { useTermUI } from './store'

/** `label` '' = the session's topic folder. */
export type TermPlace = { path: string; label: string }

/** Tokens of terminals just opened (the open call returns one): the view uses it instead of asking again. */
const fresh = new Map<string, string>()
const MIN_H = 140

type ViewApi = { selection: () => string; focus: () => void; send: (s: string) => void }

export default function TermDrawer({ sid, places, onQuote, onHide }: { sid: string; places: TermPlace[]; onQuote: (text: string) => void; onHide: () => void }) {
  const t = useT()
  const qc = useQueryClient()
  const mobile = useIsMobile()
  const drawer = useTermUI((s) => s.bySid[sid])
  const ui = useTermUI.getState
  const { data } = useTermState()
  const ids = React.useMemo(() => drawer?.ids ?? [], [drawer?.ids])
  const active = drawer?.active ?? ids[ids.length - 1]
  const views = React.useRef(new Map<string, ViewApi>())
  const [hasSel, setHasSel] = React.useState(false)
  const opening = React.useRef(false)

  // the server's list is the truth: a terminal closed elsewhere (or a restarted server) leaves the tabs
  React.useEffect(() => {
    if (data) ui().keepOnly(data.terms.map((x) => x.id))
  }, [data, ui])

  const open = React.useCallback(
    async (cwd: string) => {
      if (opening.current) return
      opening.current = true
      try {
        const r = await termApi.open(cwd, 100, 24)
        fresh.set(r.id, r.token)
        ui().add(sid, r.id)
        void qc.invalidateQueries({ queryKey: termKey })
      } catch (e) {
        toast.error(t('term.openFailed'), isApiError(e, 'too_many') ? t('term.tooMany') : errorMessage(e))
      } finally {
        opening.current = false
      }
    },
    [sid, qc, t, ui],
  )

  // opened with no terminal: one in the first place (the session's repository, else its topic folder)
  const firstPlace = places[0]?.path
  React.useEffect(() => {
    if (data && !ids.length && firstPlace) void open(firstPlace)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the list is known
  }, [!!data])

  const close = async (id: string) => {
    ui().remove(id)
    views.current.delete(id)
    try {
      await termApi.close(id)
    } catch {
      /* gone already */
    }
    void qc.invalidateQueries({ queryKey: termKey })
    if (ids.length <= 1) onHide()
  }
  const closeAll = async () => {
    for (const id of data?.terms.map((x) => x.id) ?? []) {
      ui().remove(id)
      await termApi.close(id).catch(() => undefined)
    }
    void qc.invalidateQueries({ queryKey: termKey })
    onHide()
  }
  const quote = () => {
    const s = active ? views.current.get(active)?.selection() : ''
    if (s?.trim()) onQuote('```\n' + s.replace(/\s+$/, '') + '\n```')
  }

  // height: drag the top edge (desktop); a phone takes most of the column
  const [h, setH] = React.useState(drawer?.height ?? 280)
  const drag = (e: React.PointerEvent) => {
    const y0 = e.clientY
    const h0 = h
    const move = (ev: PointerEvent) => setH(Math.max(MIN_H, Math.min(window.innerHeight * 0.8, h0 + (y0 - ev.clientY))))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setH((v) => {
        ui().setHeight(sid, v)
        return v
      })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const title = (id: string) => data?.terms.find((x) => x.id === id)?.title ?? '…'
  const total = data?.terms.length ?? 0

  return (
    <div className="relative flex shrink-0 flex-col border-t bg-background" style={{ height: mobile ? '58dvh' : h }} data-testid="term-drawer">
      {!mobile && <div className="absolute inset-x-0 -top-1 z-10 h-2 cursor-row-resize" onPointerDown={drag} aria-hidden />}
      <div className="flex h-9 shrink-0 items-center gap-1 border-b px-1.5">
        <SquareTerminal className="ml-1 size-3.5 shrink-0 text-muted-foreground" />
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto" role="tablist">
          {ids.map((id) => (
            <div
              key={id}
              role="tab"
              aria-selected={id === active}
              className={cn('group/tab flex h-7 shrink-0 items-center gap-1 rounded-md pr-0.5 pl-2 text-xs', id === active ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/60')}
            >
              <button type="button" className="max-w-36 truncate outline-none" onClick={() => ui().setActive(sid, id)}>
                <Sensitive>{title(id)}</Sensitive>
              </button>
              <button type="button" className="rounded p-0.5 opacity-60 hover:bg-background hover:opacity-100" aria-label={t('term.close')} onClick={() => void close(id)}>
                <X className="size-3" />
              </button>
            </div>
          ))}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="size-7" aria-label={t('term.new')} data-testid="term-new">
                <Plus className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {places.map((p) => (
                <DropdownMenuItem key={p.path} onSelect={() => void open(p.path)}>
                  <Sensitive>{p.label || t('term.topicFolder')}</Sensitive>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {hasSel && (
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={quote} data-testid="term-quote">
            <MessageSquareQuote className="size-3.5" />
            <span className="max-md:sr-only">{t('term.quote')}</span>
          </Button>
        )}
        {total > 1 && (
          <button type="button" className="shrink-0 px-1 text-[11px] text-muted-foreground hover:text-foreground max-md:hidden" onClick={() => void closeAll()}>
            {t('term.openCount', { count: total })} · {t('term.closeAll')}
          </button>
        )}
        <Tooltip content={`${t('term.hide')} (Ctrl+J)`}>
          <Button variant="ghost" size="icon-sm" className="size-7" aria-label={t('term.hide')} onClick={onHide}>
            <ChevronDown className="size-4" />
          </Button>
        </Tooltip>
      </div>
      <div className="relative min-h-0 flex-1">
        {ids.map((id) => (
          <XtermView
            key={id}
            id={id}
            visible={id === active}
            onSelection={(s) => id === active && setHasSel(!!s)}
            onGone={() => {
              ui().remove(id)
              void qc.invalidateQueries({ queryKey: termKey })
            }}
            register={(api) => (api ? views.current.set(id, api) : views.current.delete(id))}
          />
        ))}
        {!ids.length && <p className="p-4 text-xs text-muted-foreground">{t('term.opening')}</p>}
      </div>
      {mobile && active && <KeyBar send={(s) => views.current.get(active)?.send(s)} />}
    </div>
  )
}

function themeOf(el: HTMLElement) {
  const cs = getComputedStyle(el)
  return { background: cs.backgroundColor, foreground: cs.color, cursor: cs.color, selectionBackground: 'rgba(120,150,255,0.35)' }
}

function XtermView({ id, visible, onSelection, onGone, register }: { id: string; visible: boolean; onSelection: (s: string) => void; onGone: () => void; register: (api: ViewApi | null) => void }) {
  const t = useT()
  const box = React.useRef<HTMLDivElement>(null)
  const live = React.useRef({ onSelection, onGone, visible, t })
  live.current = { onSelection, onGone, visible, t }
  const fitRef = React.useRef<FitAddon | null>(null)
  const termRef = React.useRef<Terminal | null>(null)

  React.useEffect(() => {
    const el = box.current!
    const term = new Terminal({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      cursorBlink: true,
      scrollback: 5000,
      allowProposedApi: false,
      theme: themeOf((el.closest('[data-testid=term-drawer]') as HTMLElement | null) ?? el),
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(el)
    termRef.current = term
    fitRef.current = fit
    // Ctrl+J toggles the drawer (the column listens): xterm lets it through
    term.attachCustomKeyEventHandler((e) => !(e.ctrlKey && !e.altKey && !e.metaKey && e.key.toLowerCase() === 'j'))
    let ws: WebSocket | null = null
    let alive = true
    let tries = 0
    const send = (o: object) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify(o))
    const connect = async () => {
      let token = fresh.get(id)
      fresh.delete(id)
      if (!token) {
        try {
          token = (await termApi.token(id)).token
        } catch {
          if (alive) live.current.onGone()
          return
        }
      }
      if (!alive) return
      ws = new WebSocket(termSocketUrl(id, token))
      ws.binaryType = 'arraybuffer'
      let first = true
      ws.onopen = () => {
        tries = 0
        try {
          fit.fit()
        } catch {
          /* hidden */
        }
        send({ r: [term.cols, term.rows] })
      }
      ws.onmessage = (ev) => {
        if (first) {
          term.reset() // the server replays everything since the start
          first = false
        }
        term.write(new Uint8Array(ev.data as ArrayBuffer))
      }
      ws.onclose = (ev) => {
        if (!alive) return
        if (ev.code === 4000) {
          term.write(`\r\n\x1b[2m${live.current.t('term.ended')}\x1b[0m\r\n`)
          window.setTimeout(() => alive && live.current.onGone(), 1200)
          return
        }
        if (tries++ < 20) window.setTimeout(() => alive && void connect(), Math.min(5000, 400 * tries))
      }
    }
    void connect()
    const d1 = term.onData((d) => send({ i: d }))
    const d2 = term.onResize(({ cols, rows }) => send({ r: [cols, rows] }))
    const d3 = term.onSelectionChange(() => live.current.onSelection(term.getSelection()))
    const ro = new ResizeObserver(() => {
      if (!live.current.visible) return
      try {
        fit.fit()
      } catch {
        /* not laid out */
      }
    })
    ro.observe(el)
    register({ selection: () => term.getSelection(), focus: () => term.focus(), send: (s) => send({ i: s }) })
    return () => {
      alive = false
      register(null)
      ro.disconnect()
      d1.dispose()
      d2.dispose()
      d3.dispose()
      ws?.close()
      term.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one terminal per id
  }, [id])

  React.useEffect(() => {
    if (!visible) return
    try {
      fitRef.current?.fit()
    } catch {
      /* not laid out */
    }
    termRef.current?.focus()
  }, [visible])

  return <div ref={box} className={cn('absolute inset-0 px-1.5 pt-1', !visible && 'invisible')} data-testid="term-view" />
}

/** Keys a phone keyboard lacks (a tap keeps the keyboard open: the terminal keeps the focus). */
function KeyBar({ send }: { send: (s: string) => void }) {
  const keys: [string, string][] = [
    ['Esc', '\x1b'],
    ['Tab', '\t'],
    ['Ctrl+C', '\x03'],
    ['Ctrl+D', '\x04'],
    ['←', '\x1b[D'],
    ['↑', '\x1b[A'],
    ['↓', '\x1b[B'],
    ['→', '\x1b[C'],
  ]
  return (
    <div className="flex shrink-0 gap-1 overflow-x-auto border-t px-1.5 py-1" data-testid="term-keys">
      {keys.map(([label, seq]) => (
        <button key={label} type="button" onPointerDown={(e) => e.preventDefault()} onClick={() => send(seq)} className="h-9 min-w-10 shrink-0 rounded-md border bg-muted/40 px-2 font-mono text-xs active:bg-accent">
          {label}
        </button>
      ))}
    </div>
  )
}
