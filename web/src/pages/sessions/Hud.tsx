// HUD: a minimal floating window for one session - the prompt; while Claude works, the prompt and its
// last 3 execution lines; when it is done, its answer with the images it points to (‹ › between them);
// an optional shared screen (a frame is attached to each message, Claude may send it back annotated).
// Chrome/Edge: Document Picture-in-Picture (always on top, over every app, movable anywhere).
// Elsewhere: a small popup window on /sessions/hud/<id> renders the same bar.
import * as React from 'react'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowUp, Brain, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, CornerDownRight, ExternalLink, ListChecks, Loader2, MessageSquare, Monitor, Play, Square, User, Wrench, X } from 'lucide-react'
import { uploadAttachment, useSendMessage, useSessionSeeded, useSettings, useSteerSession, useStopSession } from '@/lib/queries'
import { Markdown } from '@/components/ui/markdown'
import { errorMessage } from '@/lib/api'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { useSessionLog, type Item } from './log'
import { usePending } from './store'
import { useApprove } from './Plan'
import { baseName, FILE_HREF, isImage, isVideo, linkifyMarkdown, mediaPaths } from './util'
import { Thumb } from '@/features/files/Thumb'

const W = 520
const H_BAR = 188
const H_OPEN = 440
const PENDING_MAX_MS = 30_000

/* ---------------------------------------------------------------- opener */

type DocPiP = { requestWindow: (o: { width: number; height: number }) => Promise<Window>; window: Window | null }
const docPiP = (): DocPiP | null => (window as unknown as { documentPictureInPicture?: DocPiP }).documentPictureInPicture ?? null

/** Always-on-top window available (Chrome/Edge 116+); otherwise the HUD opens in a popup. */
export const hudOnTop = () => !!docPiP()

function mirrorDocument(to: Document) {
  for (const n of document.head.querySelectorAll('link[rel="stylesheet"], style')) {
    if (n instanceof HTMLLinkElement) {
      const l = to.createElement('link')
      l.rel = 'stylesheet'
      l.href = n.href // absolute: the PiP document has no base URL of its own
      to.head.appendChild(l)
    } else to.head.appendChild(n.cloneNode(true))
  }
  const sync = () => {
    const src = document.documentElement
    const dst = to.documentElement
    dst.className = src.className
    dst.lang = src.lang
    dst.setAttribute('style', src.getAttribute('style') || '')
    for (const k of ['accent', 'density']) dst.dataset[k] = src.dataset[k]
  }
  sync()
  // Theme / accent changed in the app → the HUD follows.
  const mo = new MutationObserver(sync)
  mo.observe(document.documentElement, { attributes: true })
  return () => mo.disconnect()
}

/** Opens the HUD of a session. Returns false when nothing could be opened (popup blocked). */
/** `go(path)`: shows an app route (a file, a page) in the main window. */
export async function openHud(sid: string, qc: QueryClient, go: (path: string) => void): Promise<boolean> {
  const pip = docPiP()
  if (!pip) {
    const w = window.open(`/sessions/hud/${encodeURIComponent(sid)}`, `mx-hud-${sid}`, `popup,width=${W},height=${H_OPEN + 40}`)
    return !!w
  }
  pip.window?.close() // one PiP window per tab: the new session replaces the previous one
  const win = await pip.requestWindow({ width: W, height: H_OPEN })
  const stop = mirrorDocument(win.document)
  win.document.title = 'HUD'
  const el = win.document.createElement('div')
  el.style.height = '100%'
  win.document.body.appendChild(el)
  const root = createRoot(el)
  root.render(
    <QueryClientProvider client={qc}>
      <ErrorBoundary>
        <HudBar sid={sid} win={win} onOpen={go} onOpenApp={() => window.focus()} />
      </ErrorBoundary>
    </QueryClientProvider>,
  )
  win.addEventListener('pagehide', () => {
    stop()
    root.unmount()
  })
  return true
}

/* ---------------------------------------------------------------- screen share */

type Share = { stream: MediaStream; video: HTMLVideoElement }

async function startShare(win: Window): Promise<Share> {
  // A click in a PiP window also activates its opener: either navigator can ask.
  const md = win.navigator.mediaDevices ?? navigator.mediaDevices
  const stream = await md.getDisplayMedia({ video: { frameRate: 2 }, audio: false })
  // Kept in the document (invisible): a detached <video> may never decode a frame.
  const video = win.document.createElement('video')
  video.muted = true
  video.playsInline = true
  video.setAttribute('aria-hidden', 'true')
  video.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none'
  video.srcObject = stream
  win.document.body.appendChild(video)
  try {
    await video.play()
  } catch (e) {
    stopShare({ stream, video }) // never leave the screen shared when the HUD could not use it
    throw e
  }
  return { stream, video }
}

function stopShare(share: Share) {
  share.stream.getTracks().forEach((tr) => tr.stop())
  share.video.srcObject = null
  share.video.remove()
}

/** Waits (≤ 2 s) until the shared screen has delivered a frame. */
async function frameReady(video: HTMLVideoElement): Promise<boolean> {
  for (let i = 0; i < 40 && !(video.videoWidth && video.readyState >= 2); i++) await new Promise((r) => setTimeout(r, 50))
  return !!video.videoWidth
}

/** Current frame of the shared screen, at most 1600 px wide, as WebP. Throws when none can be read. */
async function grabFrame(video: HTMLVideoElement): Promise<File> {
  if (!(await frameReady(video))) throw new Error('no-frame')
  const vw = video.videoWidth
  const vh = video.videoHeight
  const s = Math.min(1, 1600 / vw)
  const c = document.createElement('canvas')
  c.width = Math.round(vw * s)
  c.height = Math.round(vh * s)
  c.getContext('2d')?.drawImage(video, 0, 0, c.width, c.height)
  const blob = await new Promise<Blob | null>((r) => c.toBlob(r, 'image/webp', 0.85))
  if (!blob) throw new Error('no-frame')
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  const ext = blob.type === 'image/webp' ? 'webp' : 'png' // browsers without a WebP encoder give PNG
  return new File([blob], `screen-${stamp}.${ext}`, { type: blob.type })
}

/* ---------------------------------------------------------------- lines */

type Line = { key: string; kind: 'tool' | 'error' | 'think' | 'say' | 'user'; text: string }

const clean = (s: string) => s.replace(/^[\s#>*_`-]+/, '').replace(/[*_`]+/g, '').trim()
const lastLine = (s: string) => clean(s.trim().split('\n').filter((l) => l.trim()).pop() || '')
const firstLine = (s: string) => clean(s.trim().split('\n')[0] || '')

function lastLines(items: Item[], n = 3): Line[] {
  const out: Line[] = []
  for (let i = items.length - 1; i >= 0 && out.length < n; i--) {
    const it = items[i]
    if (it.kind === 'tool') out.push({ key: it.key, kind: it.result?.is_error ? 'error' : 'tool', text: it.use.summary || it.use.name })
    else if (it.kind === 'thinking') out.push({ key: it.key, kind: 'think', text: lastLine(it.ev.text) })
    else if (it.kind === 'assistant') out.push({ key: it.key, kind: 'say', text: lastLine(it.ev.text) })
    else if (it.kind === 'user') out.push({ key: it.key, kind: 'user', text: firstLine(it.ev.text) })
    else if (it.kind === 'note' && it.ev.level === 'error') out.push({ key: it.key, kind: 'error', text: firstLine(it.ev.text) })
  }
  return out.filter((l) => l.text).reverse()
}

/** The last prompt and what Claude wrote after it. */
function lastTurn(items: Item[]): { prompt: Extract<Item, { kind: 'user' }> | null; answer: string; done: boolean } {
  const parts: string[] = []
  let done = false
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'user') return { prompt: it, answer: parts.filter(Boolean).join('\n\n'), done }
    // A system turn (compact / hand off summary): no prompt or answer of the user's to show.
    if (it.kind === 'request') return { prompt: null, answer: '', done }
    if (it.kind === 'assistant') parts.unshift(it.ev.text.trim())
    if (it.kind === 'result') done = true
  }
  return { prompt: null, answer: parts.filter(Boolean).join('\n\n'), done }
}

const LINE_ICON = { tool: Wrench, error: AlertCircle, think: Brain, say: MessageSquare, user: User }

/* ---------------------------------------------------------------- media + answer */

/** Images / videos one at a time, ‹ › to go through them; a click opens the file in the app. */
function MediaStrip({ paths, onOpen }: { paths: string[]; onOpen: (path: string) => void }) {
  const t = useT()
  const [i, setI] = React.useState(0)
  React.useEffect(() => setI(0), [paths])
  const p = paths[Math.min(i, paths.length - 1)]
  if (!p) return null
  const n = paths.length
  return (
    <div className="relative mb-2 overflow-hidden rounded-lg border bg-muted/40 animate-in">
      <button type="button" onClick={() => onOpen(p)} className="block w-full focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" title={t('hud.openFile')}>
        <Thumb key={p} path={p} w={1040} alt={baseName(p)} className="mx-auto max-h-56 w-auto object-contain animate-in" />
        {isVideo(p) && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/25">
            <Play className="size-7 fill-white text-white" />
          </span>
        )}
      </button>
      {n > 1 && (
        <>
          <button type="button" className={cn(NAV_BTN, 'left-1.5')} aria-label={t('hud.prev')} onClick={() => setI((i - 1 + n) % n)}>
            <ChevronLeft className="size-4" />
          </button>
          <button type="button" className={cn(NAV_BTN, 'right-1.5')} aria-label={t('hud.next')} onClick={() => setI((i + 1) % n)}>
            <ChevronRight className="size-4" />
          </button>
          <span className="absolute bottom-1.5 left-1/2 -translate-x-1/2 rounded-full bg-black/55 px-1.5 text-[10px] text-white tabular-nums">
            {i + 1} / {n}
          </span>
        </>
      )}
    </div>
  )
}

function AnswerView({ text, filesRoot, onOpen }: { text: string; filesRoot: string | null; onOpen: (path: string) => void }) {
  const t = useT()
  const media = React.useMemo(() => mediaPaths(text, filesRoot), [text, filesRoot])
  // A line that is only the path of a media shown above adds nothing: dropped.
  const md = React.useMemo(() => {
    const shown = new Set(media)
    const kept = text.split('\n').filter((l) => !shown.has(l.trim().replace(/^[-*]\s+/, '').replace(/^`(.*)`$/, '$1')))
    return linkifyMarkdown(kept.join('\n').replace(/\n{3,}/g, '\n\n'), filesRoot)
  }, [text, media, filesRoot])
  const onLink = React.useCallback(
    (href: string) => {
      if (href.startsWith(FILE_HREF)) return () => onOpen(`/files?path=${encodeURIComponent(decodeURIComponent(href.slice(FILE_HREF.length)))}`)
      if (href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/api/')) return () => onOpen(href)
      return null
    },
    [onOpen],
  )
  return (
    <div className="group/answer relative">
      <MediaStrip paths={media} onOpen={(p) => onOpen(`/files?path=${encodeURIComponent(p)}`)} />
      <Markdown onLink={onLink} className="mx-assistant text-[13px]">
        {md}
      </Markdown>
      <button
        type="button"
        className={cn(ICON_BTN, 'absolute top-0 right-0 bg-background/80 opacity-0 group-hover/answer:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100')}
        title={t('common.copy')}
        aria-label={t('common.copy')}
        onClick={() => void copyText(text)}
      >
        <Copy className="size-3.5" />
      </button>
    </div>
  )
}

/** While Claude works: the prompt it is working on (and the capture sent with it). */
function PromptEcho({ item }: { item: Extract<Item, { kind: 'user' }> }) {
  const shots = item.ev.attachments.filter(isImage)
  return (
    <div className="flex min-w-0 items-start gap-2 animate-in">
      {shots[0] && <Thumb path={shots[0]} w={320} className="h-12 w-auto shrink-0 rounded-md border object-cover" />}
      <p className="line-clamp-3 min-w-0 text-[13px] text-foreground/85">{item.ev.text}</p>
    </div>
  )
}

/* ---------------------------------------------------------------- bar */

export function HudBar({ sid, win, onOpen, onOpenApp }: { sid: string; win: Window; onOpen: (path: string) => void; onOpenApp?: () => void }) {
  const t = useT()
  const { data: session } = useSessionSeeded(sid)
  const { data: settings } = useSettings()
  const log = useSessionLog(sid)
  const send = useSendMessage()
  const stop = useStopSession()
  const steer = useSteerSession()
  const [approvePlan, approving] = useApprove(sid)
  const [draft, setDraft] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  // open: the answer (or the prompt being worked on) above the steps · closed: a slim bar with the steps.
  const [open, setOpen] = React.useState(true)
  const [share, setShare] = React.useState<Share | null>(null)
  const input = React.useRef<HTMLTextAreaElement>(null)
  const scroller = React.useRef<HTMLDivElement>(null)

  const lines = React.useMemo(() => lastLines(log.items), [log.items])
  const turn = React.useMemo(() => lastTurn(log.items), [log.items])
  // Faster than the session state: the turn's `result` event ends it (the answer shows at once), and a
  // message just sent counts as running before its `user` event is in the log.
  // (A pending message whose `user` event never came - log reloaded, text changed - stops counting after 30 s.)
  const pendingAt = usePending((s) => s.bySession[sid]?.find((p) => !p.queued)?.at ?? 0)
  const [, tick] = React.useReducer((n: number) => n + 1, 0)
  React.useEffect(() => {
    if (!pendingAt) return
    const id = setTimeout(tick, Math.max(0, pendingAt + PENDING_MAX_MS - Date.now()) + 50)
    return () => clearTimeout(id)
  }, [pendingAt])
  const sending = !!pendingAt && Date.now() - pendingAt < PENDING_MAX_MS
  const running = sending || (session?.state === 'running' && !turn.done)
  const filesRoot = settings?.files_root || null

  // A new answer starts at its top.
  React.useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [turn.prompt?.key, running])

  // The shared screen stops with the window (or from the browser's "Stop sharing" bar).
  React.useEffect(() => {
    if (!share) return
    const track = share.stream.getVideoTracks()[0]
    const ended = () => setShare(null)
    track?.addEventListener('ended', ended)
    return () => {
      track?.removeEventListener('ended', ended)
      stopShare(share)
    }
  }, [share])

  React.useEffect(() => {
    input.current?.focus()
  }, [])

  // The window title (task bar, window switcher) is the session's.
  React.useEffect(() => {
    if (session?.title) win.document.title = `${session.title} · HUD`
  }, [session?.title, win])

  // Resizing a PiP window needs a click / key press: done on toggle and on send, never on its own.
  const resize = (h: number) => {
    try {
      if (Math.abs(win.innerHeight - h) > 8) win.resizeTo(win.outerWidth, h + (win.outerHeight - win.innerHeight))
    } catch {
      /* refused: the content scrolls */
    }
  }
  const toggleOpen = () => {
    setOpen(!open)
    resize(open ? H_BAR : H_OPEN)
  }

  const alive = React.useRef(true)
  React.useEffect(
    () => () => {
      alive.current = false
    },
    [],
  )
  const toggleShare = async () => {
    setError(null)
    if (share) return setShare(null)
    try {
      const s = await startShare(win)
      // The HUD was closed while the browser's picker was open: nothing would ever stop that stream.
      if (alive.current) setShare(s)
      else stopShare(s)
    } catch (e) {
      if ((e as DOMException)?.name !== 'NotAllowedError') setError(errorMessage(e))
    }
  }

  const submit = async () => {
    const text = draft.trim()
    if (!text || busy || !session) return
    if (open && win.innerHeight < H_OPEN - 40) resize(H_OPEN) // room for the answer to come
    setBusy(true)
    setError(null)
    const { add, remove } = usePending.getState()
    let lid: string | null = null
    try {
      const attachments: string[] = []
      if (share) {
        // Screen shared but no capture: say so rather than sending without it.
        const frame = await grabFrame(share.video).catch(() => {
          throw new Error(t('hud.noFrame'))
        })
        attachments.push((await uploadAttachment(session.path, frame)).path)
      }
      lid = add(sid, { text, attachments, queued: running })
      const r = await send.mutateAsync({ id: sid, text, attachments, hud: true })
      if (r.queued !== running) {
        remove(sid, lid)
        add(sid, { text, attachments, queued: r.queued })
      }
      setDraft('')
    } catch (e) {
      if (lid) remove(sid, lid)
      setError(errorMessage(e))
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  const onStop = () => stop.mutate(sid, { onSuccess: () => usePending.getState().clearQueued(sid) })
  const queue = session?.queue ?? 0
  const canStop = running && !draft.trim()
  const showAnswer = open && !running && !!turn.answer
  const showSteps = !open || running || !turn.answer

  return (
    <div className="flex h-full flex-col gap-2 bg-background p-2.5 text-foreground">
      {/* status */}
      <div className="flex h-5 min-w-0 shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
        <span className="relative flex size-2 shrink-0">
          {running && <span className="absolute inset-0 animate-[mx-ping_1.4s_ease-out_infinite] rounded-full bg-primary" />}
          <span className={cn('relative size-2 rounded-full', running ? 'bg-primary' : 'bg-muted-foreground/50')} />
        </span>
        <span className="min-w-0 truncate font-medium text-foreground/80">{session?.title ?? '…'}</span>
        {share && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-destructive/15 px-1.5 py-px text-[10px] font-medium text-destructive">
            <span className="size-1.5 rounded-full bg-destructive" /> {t('hud.sharing')}
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-0.5">
          {onOpenApp && (
            <button type="button" className={ICON_BTN} title={t('hud.openApp')} aria-label={t('hud.openApp')} onClick={onOpenApp}>
              <ExternalLink className="size-3.5" />
            </button>
          )}
          <button type="button" className={ICON_BTN} title={t('hud.close')} aria-label={t('hud.close')} onClick={() => win.close()}>
            <X className="size-3.5" />
          </button>
        </span>
      </div>

      {/* answer when done · prompt being worked on while running */}
      {open && (showAnswer || (running && turn.prompt)) && (
        <div ref={scroller} className={cn('min-h-0 overflow-y-auto overscroll-contain rounded-lg border bg-card px-3 py-2', showAnswer ? 'flex-1' : 'shrink-0')}>
          {showAnswer ? <AnswerView key={turn.prompt?.key} text={turn.answer} filesRoot={filesRoot} onOpen={onOpen} /> : turn.prompt && <PromptEcho item={turn.prompt} />}
        </div>
      )}

      {/* last 3 execution lines */}
      {showSteps && (
        <ol className="grid min-w-0 flex-1 content-end gap-0.5 text-xs" aria-live="polite">
          {lines.length === 0 && <li className="text-muted-foreground">{log.status === 'loading' ? '…' : t('hud.empty')}</li>}
          {lines.map((l, i) => {
            const Icon = LINE_ICON[l.kind]
            const live = running && i === lines.length - 1
            return (
              <li key={l.key} className={cn('flex min-w-0 items-center gap-1.5 text-muted-foreground animate-in', live && 'text-foreground', l.kind === 'error' && 'text-destructive')}>
                {live ? <Loader2 className="size-3 shrink-0 animate-spin text-primary" /> : <Icon className="size-3 shrink-0 opacity-70" />}
                <span className={cn('truncate', live && 'animate-[mx-shimmer_1.6s_ease-in-out_infinite]')}>{l.text}</span>
              </li>
            )
          })}
        </ol>
      )}

      {/* waiting messages */}
      {running && queue > 0 && (
        <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground animate-in">
          <span className="truncate">{t('sessions.queue.count', { count: queue })}</span>
          <button
            type="button"
            onClick={() => steer.mutate(sid)}
            disabled={steer.isPending}
            className="ml-auto inline-flex h-6 shrink-0 items-center gap-1 rounded-md bg-primary px-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            <CornerDownRight className="size-3" /> {t('sessions.queue.steerShort')}
          </button>
        </div>
      )}

      {/* plan mode: Claude's plan waits for the user's validation */}
      {session?.plan_ready && !running && (
        <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground animate-in">
          <ListChecks className="size-3.5 shrink-0 text-primary" />
          <span className="truncate">{t('plan.readyTitle')}</span>
          <button
            type="button"
            onClick={approvePlan}
            disabled={approving}
            className="ml-auto inline-flex h-6 shrink-0 items-center gap-1 rounded-md bg-primary px-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            <Check className="size-3" /> {t('plan.hudApprove')}
          </button>
        </div>
      )}

      {error && <p className="shrink-0 truncate text-[11px] text-destructive" title={error}>{error}</p>}

      {/* prompt */}
      <form
        className="flex shrink-0 items-end gap-1 rounded-xl border bg-card p-1 shadow-xs transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/20"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <button
          type="button"
          className={cn(ICON_BTN, 'size-8', share && 'bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary')}
          title={share ? t('hud.shareStop') : t('hud.share')}
          aria-label={share ? t('hud.shareStop') : t('hud.share')}
          aria-pressed={!!share}
          onClick={() => void toggleShare()}
        >
          <Monitor className="size-4" />
        </button>
        <textarea
          ref={input}
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void submit()
            }
          }}
          placeholder={running ? t('hud.placeholderRunning') : session?.plan_mode ? t(session.plan_ready ? 'plan.placeholderAdjust' : 'plan.placeholder') : t('hud.placeholder')}
          className="max-h-24 min-h-8 flex-1 resize-none bg-transparent px-1 py-1.5 text-sm outline-none placeholder:text-muted-foreground [field-sizing:content]"
        />
        <button type="button" className={cn(ICON_BTN, 'size-8')} title={open ? t('hud.collapse') : t('hud.expand')} aria-label={open ? t('hud.collapse') : t('hud.expand')} aria-expanded={open} onClick={toggleOpen}>
          {open ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </button>
        {canStop ? (
          <button type="button" className={ROUND_BTN} title={t('sessions.stop')} aria-label={t('sessions.stop')} onClick={onStop} disabled={stop.isPending}>
            <Square className="size-3.5 fill-current" />
          </button>
        ) : (
          <button type="submit" className={ROUND_BTN} title={t('hud.send')} aria-label={t('hud.send')} disabled={!draft.trim() || busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
          </button>
        )}
      </form>
    </div>
  )
}

const ICON_BTN =
  'inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const ROUND_BTN =
  'inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-[background-color,opacity] hover:bg-primary/90 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const NAV_BTN =
  'absolute top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white transition-colors hover:bg-black/75 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
