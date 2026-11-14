// Preview card of a session, shown to the right of the sidebar's sessions rail (hover a row with a mouse, or focus it
// from the keyboard): title, place, state, model, then the last exchange. The data is the thread's own first load:
// `prefetchTail` starts it and the card reads it without consuming it, so opening the session right after uses the
// same request. Polled (a small tail) only while the card is open on a running session.
// A running session also gets, at the bottom, the thread's own working rows (pages/sessions/PreviewWorking.tsx,
// lazy): last tool cards, running sub-agents with what they do now, the running line with its timer, live from that
// session's stream while the card is open.
// Rendered in a portal (the bar is overflow-hidden) but as a React child of the rail: pointer enter / leave through
// the portal count as staying inside the bar, so hovering the card keeps the bar unfolded and leaving it folds it.
// No focus is ever moved into it, and nothing in it sets aria-expanded (the bar waits for those before folding).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { fetchTail, peekEarlyTail, prefetchTail, TAIL_EVENTS } from '@/lib/queries'
import type { Session, SessionEvent, SessionEventsBackPage } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { useLang, useT, withGroups } from '@/i18n'
import { Sensitive, Skeleton, SkeletonText, StatusDot } from '@/components/ui'

const CARD_W = 340
/** Wider for a running session: its tool cards read like in the thread. */
const CARD_W_RUNNING = 400
const CARD_MAX_H = 360
/** A running session's card also holds its working block. */
const CARD_MAX_H_RUNNING = 384
/** The working block of a running session (tool cards, sub-agents, running line): the Sessions page's own rows,
 *  lazy-loaded with that page's chunk (the rail's tree comes from it too), so the shell stays light. */
const PreviewWorking = React.lazy(withGroups(['files'], () => import('@/pages/sessions/PreviewWorking')))
/** Events read on each poll of a running session (the full first page comes from the thread's own load). */
const POLL_EVENTS = 40
/** The working rows' live stream opens after the card has been shown this long. */
const STREAM_DELAY_MS = 400

type Preview = { user: string | null; assistant: string | null; activity: string | null; model: string | null; at: number | null }

/** "Opus 4.1" from "claude-opus-4-1-…" (the Sessions page's `modelLabel`, kept here: the shell stays in the core chunk). */
function modelLabel(id: string | null | undefined): string {
  if (!id) return ''
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d+))?/.exec(id)
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] && m[3].length <= 2 ? `.${m[3]}` : ''}` : id
}

/** Markdown read as plain text: enough for a few clamped lines. */
function plain(md: string): string {
  return md
    .replace(/```[\s\S]*?(```|$)/g, ' … ')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/(\*\*|__|`|~~)/g, '')
    .replace(/^\s*\|?[-:| ]+\|?\s*$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** The last exchange of a tail (falls back on `prev` for what a short poll window no longer holds). */
function summarize(events: SessionEvent[], prev?: Preview): Preview {
  const hidden = new Set<number>()
  for (const e of events) if (e.type === 'hide') (e.hidden ? hidden.add(e.ref) : hidden.delete(e.ref))
  let u = -1
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.type === 'user' && !hidden.has(e.at) && (e.text.trim() || e.attachments.length)) {
      u = i
      break
    }
  }
  let assistant: string | null = null
  let activity: string | null = null
  let model: string | null = null
  let at: number | null = null
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    at ??= e.at
    if (e.type === 'assistant' && assistant === null && e.text.trim()) assistant = e.text
    else if (e.type === 'tool_use' && activity === null && i > u) activity = e.summary || e.name
    else if (e.type === 'thinking' && activity === null && i > u) activity = '…'
    else if ((e.type === 'result' || e.type === 'init') && !model && e.model) model = e.model
  }
  // the answer to the last message, or (nothing yet) the previous answer when the turn is over
  const lastAssistant = events.findLastIndex((e) => e.type === 'assistant' && e.text.trim().length > 0)
  const ue = u >= 0 ? (events[u] as Extract<SessionEvent, { type: 'user' }>) : null
  const user = ue ? ue.text.trim() || ue.attachments.map((a) => a.split('/').pop()).join(', ') : null
  return {
    user: user ?? prev?.user ?? null,
    assistant: lastAssistant > u || u < 0 ? (assistant ?? prev?.assistant ?? null) : null,
    activity,
    model: model ?? prev?.model ?? null,
    at: at ?? prev?.at ?? null,
  }
}

const previewKey = (id: string) => ['sessions', 'preview', id] as const

function useSessionPreview(id: string | null, live: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: previewKey(id || ''),
    enabled: !!id,
    staleTime: 60_000,
    gcTime: 10 * 60_000,
    // a running session's card follows its live stream (PreviewWorking): no polling on top
    refetchInterval: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }): Promise<Preview> => {
      const sid = id as string
      const prev = qc.getQueryData<Preview>(previewKey(sid))
      let page: SessionEventsBackPage
      if (prev && live) page = await fetchTail(sid, POLL_EVENTS, signal)
      else {
        prefetchTail(sid) // the thread's first load: opening the session next reuses it
        page = await (peekEarlyTail(sid) ?? fetchTail(sid, TAIL_EVENTS, signal))
      }
      return summarize(page.events || [], prev)
    },
  })
}

function reducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * The frame every preview card of the rail shares (a session here, an agent in features/agents/AgentPreview.tsx): a
 * portal beside the rail, level with `anchor`, kept inside the window, fading in, crossfading its content when
 * `swapKey` changes. The transparent left padding bridges the rail and the card: the pointer never crosses a gap.
 */
export function PreviewShell({
  anchor,
  rail,
  width,
  maxHeight,
  swapKey,
  testId,
  onPointerEnter,
  onPointerLeave,
  children,
}: {
  anchor: HTMLElement
  rail: HTMLElement
  width: number
  maxHeight: number
  swapKey: string
  testId: string
  onPointerEnter: () => void
  onPointerLeave: () => void
  children: React.ReactNode
}) {
  const card = React.useRef<HTMLDivElement>(null)
  const body = React.useRef<HTMLDivElement>(null)
  const [pos, setPos] = React.useState<{ left: number; top: number } | null>(null)

  // Place it: beside the rail, level with the row, kept inside the window (measured again when the content grows).
  const place = React.useCallback(() => {
    const el = card.current
    if (!el) return
    const r = rail.getBoundingClientRect()
    const a = anchor.getBoundingClientRect()
    const h = el.offsetHeight
    const top = Math.max(8, Math.min(a.top - 10, window.innerHeight - h - 8))
    // a narrow window (two sidebars open at 768-1023 px): over the rail rather than cut at the right edge
    const left = Math.max(8, Math.min(r.right, window.innerWidth - el.offsetWidth - 8))
    setPos((p) => (p && p.left === left && p.top === top ? p : { left, top }))
  }, [anchor, rail])
  React.useLayoutEffect(place)
  React.useEffect(() => {
    const el = card.current
    if (!el) return
    const ro = new ResizeObserver(place)
    ro.observe(el)
    window.addEventListener('resize', place)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', place)
    }
  }, [place])

  // Appears: fade + 4 px slide. Another row: a short crossfade of the content.
  const shown = pos !== null
  React.useEffect(() => {
    if (!shown || reducedMotion()) return
    card.current?.animate([{ opacity: 0, transform: 'translateX(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 160, easing: 'ease-out' })
  }, [shown])
  const first = React.useRef(true)
  React.useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (!reducedMotion()) body.current?.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 120, easing: 'ease-out' })
  }, [swapKey])

  return createPortal(
    <div
      ref={card}
      role="tooltip"
      data-testid={testId}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      className="fixed z-50 pl-2"
      style={{
        width: width + 8,
        left: pos?.left ?? -9999,
        top: pos?.top ?? 0,
        visibility: pos ? 'visible' : 'hidden',
        transition: reducedMotion() ? undefined : 'top 120ms ease-out',
      }}
    >
      <div className="mx-glass flex flex-col overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-pop" style={{ maxHeight: `min(${maxHeight}px, calc(100vh - 16px))` }}>
        <div ref={body} className="flex min-h-0 flex-col">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  )
}

/**
 * The card of a session. `anchor` = the hovered / focused row, `rail` = the rail's box (the card sits at its right
 * edge). One card for every row: switching rows moves it and crossfades the content.
 */
export function SessionPreviewCard({
  session,
  anchor,
  rail,
  root,
  onPointerEnter,
  onPointerLeave,
}: {
  session: Session
  anchor: HTMLElement
  rail: HTMLElement
  /** "project / topic" of the session. */
  root: string
  onPointerEnter: () => void
  onPointerLeave: () => void
}) {
  const t = useT()
  const lang = useLang()
  const running = session.state === 'running'
  const { data, isPending, isError } = useSessionPreview(session.id, running)

  // The live stream only once the card has stayed open a moment (a pointer passing over the rail opens nothing).
  const [streamOn, setStreamOn] = React.useState(false)
  React.useEffect(() => {
    setStreamOn(false)
    if (!running) return
    const h = window.setTimeout(() => setStreamOn(true), STREAM_DELAY_MS)
    return () => window.clearTimeout(h)
  }, [running, session.id])
  const nowLine =
              data?.activity ? (
                <p className="flex h-7 min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <StatusDot tone="running" pulse className="shrink-0" />
                  <span className="shrink-0">{t('shell.preview.now')}</span>
                  <span className="min-w-0 truncate font-mono text-[11px]">
                    <Sensitive length={16}>{data.activity}</Sensitive>
                  </span>
                </p>
              ) : null

  const where = (() => {
    const m = /^projects\/([^/]+)(?:\/topics\/([^/]+))?$/.exec(session.path)
    return !session.path ? root : m ? (m[2] ? `${m[1]} / ${m[2]}` : m[1]) : session.path
  })()
  const model = modelLabel(session.real_model || data?.model || session.model)
  const sent = session.sent_items?.length ? session.sent_items[session.sent_items.length - 1].text : null
  const user = sent || data?.user || null
  const assistant = data ? data.assistant : session.last_text || null
  const state =
    running ? <StatusDot tone="running" pulse label={t('sessions.state.running')} />
    : session.state === 'error' ? <StatusDot tone="error" label={t('sessions.state.error')} />
    : session.unread ? <StatusDot tone="unread" label={t('sessions.unreadOne')} />
    : session.source === 'cron' ? <Clock className="size-3 text-muted-foreground" aria-hidden />
    : <StatusDot tone="idle" className="size-1.5" />
  const stateText = running ? t('sessions.state.running') : session.state === 'error' ? t('sessions.state.error') : session.unread ? t('sessions.unreadOne') : null

  return (
    <PreviewShell
      anchor={anchor}
      rail={rail}
      width={running ? CARD_W_RUNNING : CARD_W}
      maxHeight={running ? CARD_MAX_H_RUNNING : CARD_MAX_H}
      swapKey={session.id}
      testId="session-preview"
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      <div className="shrink-0 border-b px-3.5 pt-3 pb-2.5">
        <p className="line-clamp-2 text-sm leading-5 font-semibold">
          <Sensitive length={14}>{session.title}</Sensitive>
        </p>
        <p className="truncate text-xs leading-4 text-muted-foreground">
          <Sensitive length={10}>{where}</Sensitive>
        </p>
        <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
          <span className="flex size-3.5 shrink-0 items-center justify-center">{state}</span>
          {stateText && <span className={running ? 'text-foreground' : session.state === 'error' ? 'text-destructive' : undefined}>{stateText}</span>}
          {stateText && model && <span aria-hidden>·</span>}
          {model && <span className="truncate">{model}</span>}
          <span aria-hidden>·</span>
          <span className="shrink-0 tabular-nums">{fmtRelative(session.updated, lang)}</span>
        </div>
      </div>
      <div className={`${running ? 'min-h-16' : 'min-h-0'} overflow-y-auto overscroll-contain px-3.5 py-2.5 text-[13px] leading-5`}>
        {isError && !data ? (
          <p className="text-xs text-muted-foreground">{t('shell.preview.error')}</p>
        ) : isPending && !assistant ? (
          <div className="grid gap-3" aria-hidden>
            <Skeleton className="h-3.5 w-1/2" />
            <SkeletonText lines={4} />
          </div>
        ) : !user && !assistant ? (
          <p className="text-xs text-muted-foreground">{t('shell.preview.empty')}</p>
        ) : (
          <div className="grid gap-2.5">
            {user ? (
              <div className="rounded-md bg-muted px-2.5 py-1.5">
                <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{t('shell.preview.you')}</p>
                <p className={`${running ? 'line-clamp-1' : 'line-clamp-3'} break-words whitespace-pre-line`}>
                  <Sensitive length={20}>{plain(user)}</Sensitive>
                </p>
              </div>
            ) : isPending ? (
              <Skeleton className="h-3.5 w-1/2" />
            ) : null}
            {assistant && (
              <div>
                <p className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{t('shell.preview.claude')}</p>
                <p className={`${running ? 'line-clamp-2' : 'line-clamp-8'} break-words whitespace-pre-line text-foreground/90`}>
                  <Sensitive length={40}>{plain(assistant)}</Sensitive>
                </p>
              </div>
            )}
          </div>
        )}
      </div>
      {running && (
        // the thread's own bottom rows while Claude works; until its chunk is there, the current tool alone
        <div className="flex max-h-[176px] shrink-0 flex-col justify-end overflow-hidden border-t bg-fill-1 px-3 pt-2 pb-0.5">
          <React.Suspense fallback={nowLine}>
            {streamOn ? <PreviewWorking session={session} /> : nowLine}
          </React.Suspense>
        </div>
      )}
    </PreviewShell>
  )
}
