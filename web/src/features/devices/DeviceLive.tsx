// One device live (WS /api/devices/<id>/live): its screen (~3 pictures a second while this is open), its state, and the
// person's hands on it. Touching the picture takes over (Claude's input is refused meanwhile): a tap / click, a long
// press, a drag (swipe), the wheel, the keyboard (computers), Back / Home / Recents (Android). "Hand back" gives it
// back to Claude with a word; when Claude asked (ask_human) the request is answered with it (done, or skip).
import * as React from 'react'
import { ChevronLeft, Circle, Hand, LayoutGrid, Minimize2, SkipForward, Undo2 } from 'lucide-react'
import { useT } from '@/i18n'
import { deviceLiveToken, useSaveDevice } from '@/lib/queries'
import type { Device, DeviceAsk } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, Input, Select, Spinner } from '@/components/ui'

type State = { device: Device; me: boolean; asks: DeviceAsk[] }
type Input_ = { a: string; x?: number; y?: number; x2?: number; y2?: number; sw?: number; sh?: number; button?: string; double?: boolean; dx?: number; dy?: number; text?: string; keys?: string; ms?: number }

const LONG_MS = 550
const DRAG_PX = 10
const KEYS: Record<string, string> = {
  Enter: 'enter', Tab: 'tab', Escape: 'escape', Backspace: 'backspace', Delete: 'delete', ArrowUp: 'up', ArrowDown: 'down',
  ArrowLeft: 'left', ArrowRight: 'right', Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown', ' ': 'space',
}

export function DeviceLive({ id, onClose, className }: { id: string; onClose?: () => void; className?: string }) {
  const t = useT()
  const [st, setSt] = React.useState<State | null>(null)
  const [src, setSrc] = React.useState('')
  const [err, setErr] = React.useState('')
  const [word, setWord] = React.useState('')
  const ws = React.useRef<WebSocket | null>(null)
  const img = React.useRef<HTMLImageElement>(null)
  const down = React.useRef<{ x: number; y: number; at: number; button: number } | null>(null)
  const wheel = React.useRef({ dx: 0, dy: 0, timer: 0 as unknown as ReturnType<typeof setTimeout> | 0 })

  React.useEffect(() => {
    let closed = false
    let url = ''
    let sock: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    const connect = async () => {
      try {
        const { token } = await deviceLiveToken()
        if (closed) return
        const proto = location.protocol === 'https:' ? 'wss' : 'ws'
        sock = new WebSocket(`${proto}://${location.host}/api/devices/${encodeURIComponent(id)}/live?t=${encodeURIComponent(token)}`)
        sock.binaryType = 'blob'
        ws.current = sock
        sock.onmessage = (ev) => {
          if (typeof ev.data === 'string') {
            try {
              const m = JSON.parse(ev.data)
              if (m.t === 'state') setSt({ device: m.device, me: !!m.me, asks: m.asks || [] })
              else if (m.t === 'error') setErr(m.text || m.code || '')
            } catch {
              /* not JSON */
            }
            return
          }
          const next = URL.createObjectURL(ev.data as Blob)
          setSrc(next)
          if (url) URL.revokeObjectURL(url)
          url = next
        }
        sock.onclose = (ev) => {
          ws.current = null
          if (!closed && ev.code !== 4404 && ev.code !== 4403) retry = setTimeout(connect, 2000)
        }
      } catch {
        if (!closed) retry = setTimeout(connect, 3000)
      }
    }
    void connect()
    return () => {
      closed = true
      clearTimeout(retry)
      sock?.close()
      if (url) URL.revokeObjectURL(url)
    }
  }, [id])

  const send = (m: object) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify(m))
  const input = (m: Input_) => {
    setErr('')
    send({ t: 'input', ...m })
  }
  /** a point of the picture shown -> pixels of the picture (its natural size), as the device expects */
  const at = (cx: number, cy: number) => {
    const el = img.current
    if (!el || !el.naturalWidth) return null
    const r = el.getBoundingClientRect()
    const x = Math.round(((cx - r.left) / r.width) * el.naturalWidth)
    const y = Math.round(((cy - r.top) / r.height) * el.naturalHeight)
    if (x < 0 || y < 0 || x > el.naturalWidth || y > el.naturalHeight) return null
    return { x, y, sw: el.naturalWidth, sh: el.naturalHeight }
  }

  const d = st?.device
  const android = d?.os === 'android'
  const online = !!d?.online
  const asks = st?.asks || []
  const me = !!st?.me

  const onPointerDown = (e: React.PointerEvent) => {
    if (!online) return
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    down.current = { x: e.clientX, y: e.clientY, at: Date.now(), button: e.button }
    e.preventDefault()
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const s = down.current
    down.current = null
    if (!s || !online) return
    const p0 = at(s.x, s.y)
    const p1 = at(e.clientX, e.clientY)
    if (!p0) return
    const moved = Math.hypot(e.clientX - s.x, e.clientY - s.y) > DRAG_PX
    const ms = Date.now() - s.at
    if (moved && p1) input({ a: 'drag', x: p0.x, y: p0.y, x2: p1.x, y2: p1.y, sw: p0.sw, sh: p0.sh, ms: Math.min(3000, Math.max(80, ms)) })
    else if (ms >= LONG_MS) input({ a: 'long_press', ...p0, ms })
    else input({ a: 'click', ...p0, button: s.button === 2 ? 'right' : s.button === 1 ? 'middle' : 'left' })
  }
  const onWheel = (e: React.WheelEvent) => {
    if (!online) return
    const p = at(e.clientX, e.clientY)
    if (!p) return
    const w = wheel.current
    w.dx += e.deltaX
    w.dy += e.deltaY
    if (w.timer) return
    w.timer = setTimeout(() => {
      const dx = Math.round(w.dx / 100)
      const dy = Math.round(w.dy / 100) || Math.sign(w.dy)
      w.dx = w.dy = 0
      w.timer = 0
      if (dx || dy) input({ a: 'scroll', ...p, dx, dy })
    }, 120)
  }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!online || android) return
    const mods = [e.ctrlKey && 'ctrl', e.altKey && 'alt', e.metaKey && 'cmd'].filter(Boolean) as string[]
    if (e.key.length === 1 && !mods.length) {
      input({ a: 'type', text: e.key })
    } else {
      const k = KEYS[e.key] || (e.key.length === 1 ? e.key.toLowerCase() : '')
      if (!k) return
      input({ a: 'key', keys: [...mods, e.shiftKey && e.key.length > 1 ? 'shift' : '', k].filter(Boolean).join('+') })
    }
    e.preventDefault()
  }
  const handBack = (done: true | 'skip' | false) => {
    send({ t: 'release', ...(done ? { done } : {}), note: word.trim() })
    setWord('')
  }

  let status: React.ReactNode = t('devices.live.connecting')
  if (d && !online) status = t('devices.live.offline')
  else if (d?.paused) status = t('devices.live.paused')
  else if (me) status = t('devices.live.youHave')
  else if (d?.claude) status = t('devices.live.claudeHas')
  else if (d?.mode === 'view') status = t('devices.live.viewOnly')
  else if (d) status = d.os_name + (d.version ? ` · Harness Link ${d.version}` : '')

  return (
    <div className={cn('flex min-h-0 flex-col bg-background', className)} data-testid="device-live">
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b px-3 py-2">
        <Circle className={cn('size-2.5 shrink-0 fill-current', online ? 'text-success' : 'text-muted-foreground')} />
        <span className="truncate text-sm font-medium">{d?.name || '…'}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">{status}</span>
        {d && <ScreenPick d={d} />}
        {online && !me && (
          <Button size="sm" variant="outline" className="h-7" onClick={() => send({ t: 'take' })} data-testid="device-take">
            <Hand /> {t('devices.live.take')}
          </Button>
        )}
        {onClose && (
          <Button size="icon-sm" variant="ghost" onClick={onClose} title={t('devices.live.close')} aria-label={t('devices.live.close')}>
            <Minimize2 />
          </Button>
        )}
      </div>
      {asks.map((a) => (
        <div key={a.id} className="flex min-w-0 items-center gap-2 border-b border-warning/40 bg-warning/8 px-3 py-1.5 text-[13px]" data-testid="device-live-ask">
          <Hand className="size-3.5 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">{t('devices.live.ask', { message: a.message })}</span>
        </div>
      ))}
      <div className="relative grid min-h-0 flex-1 place-items-center overflow-hidden bg-fill-1 p-2">
        {src ? (
          <img
            ref={img}
            src={src}
            alt={d?.name || ''}
            draggable={false}
            tabIndex={0}
            className={cn('max-h-full max-w-full touch-none select-none rounded-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring', online ? 'cursor-crosshair' : 'opacity-60')}
            onPointerDown={onPointerDown}
            onPointerUp={onPointerUp}
            onPointerCancel={() => (down.current = null)}
            onContextMenu={(e) => e.preventDefault()}
            onWheel={onWheel}
            onKeyDown={onKeyDown}
            data-testid="device-live-picture"
          />
        ) : (
          <span className="inline-flex items-center gap-2 text-[13px] text-muted-foreground">
            {d && !online ? t('devices.live.offline') : <><Spinner className="size-4" /> {t('devices.live.connecting')}</>}
          </span>
        )}
      </div>
      {err && <p className="border-t px-3 py-1 text-[12px] text-destructive">{err}</p>}
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-t px-3 py-2">
        {android && online && (
          <div className="flex items-center gap-1">
            <Button size="icon-sm" variant="ghost" onClick={() => input({ a: 'key', keys: 'back' })} title={t('devices.live.back')} aria-label={t('devices.live.back')}>
              <ChevronLeft />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => input({ a: 'key', keys: 'home' })} title={t('devices.live.home')} aria-label={t('devices.live.home')}>
              <Circle />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => input({ a: 'key', keys: 'recents' })} title={t('devices.live.recents')} aria-label={t('devices.live.recents')}>
              <LayoutGrid />
            </Button>
          </div>
        )}
        {android && online && (
          <Input
            className="h-8 min-w-32 flex-1"
            placeholder={t('devices.live.type')}
            onKeyDown={(e) => {
              const el = e.currentTarget
              if (e.key === 'Enter' && el.value) {
                input({ a: 'type', text: el.value })
                el.value = ''
                e.preventDefault()
              }
            }}
          />
        )}
        {(me || asks.length > 0) && (
          <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
            <Input className="h-8 w-56 max-w-full" value={word} onChange={(e) => setWord(e.target.value)} placeholder={t('devices.live.word')} maxLength={500} data-testid="device-word" />
            <Button size="sm" className="h-8" onClick={() => handBack(asks.length ? true : false)} data-testid="device-hand-back">
              <Undo2 /> {asks.length ? t('devices.live.done') : t('devices.live.handBack')}
            </Button>
            {asks.length > 0 && (
              <Button size="sm" variant="ghost" className="h-8" onClick={() => handBack('skip')}>
                <SkipForward /> {t('devices.live.skip')}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** Several screens: which one Claude sees and uses (and the live view shows); Claude may switch it too. */
export function ScreenPick({ d }: { d: Device }) {
  const t = useT()
  const save = useSaveDevice()
  const screens = d.hello?.screens ?? d.screens ?? []
  if (screens.length < 2) return null
  const chosen = d.display != null && d.display >= 0 ? d.display : undefined
  const cur = String(d.hello?.display ?? chosen ?? screens.find((x) => x.main)?.i ?? 0)
  return (
    <span title={t('devices.live.screenHelp')} data-testid="device-screen">
      <Select
        className="h-7 w-48 text-[12px]"
        value={cur}
        onValueChange={(v) => save.mutate({ id: d.id, display: Number(v) })}
        aria-label={t('devices.live.screen')}
        options={screens.map((x) => ({ value: String(x.i), label: `${x.name} · ${x.w}×${x.h}${x.main ? ` (${t('devices.live.main')})` : ''}` }))}
      />
    </span>
  )
}
