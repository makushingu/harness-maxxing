// Tabs mode (Sessions page, per browser; the default): one session on screen, the open sessions as chips above it.
// A chip shows its session (and whether it works, waits for you or failed); click it, Alt+←/→ or swipe on a phone to
// change; its cross closes the session. The other mode, Zones, shows the sessions side by side: going there puts the
// columns back exactly as they were (Tabs never moves them).
import * as React from 'react'
import { ChevronLeft, ChevronRight, PanelTop, X } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import type { Session } from '@/lib/types'
import { Button, Sensitive, StatusDot, Tooltip } from '@/components/ui'
import { useSessionsUI, type Col } from './store'
import { topicLabel } from './util'
import { useTabIndicator } from './tabMotion'

/** Shown first by "Next waiting": a session that finished and was not read, or stopped on an error. */
const waits = (s: Session | undefined) => !!s && s.state !== 'running' && (s.unread || s.state === 'error')

/** Computer: the one button at the top right of the page that goes from one way of showing the open sessions to the
 *  other. Tabs = one session on screen, the others as chips; Zones = the sessions next to each other (columns, grid,
 *  layouts). One icon, no text, in the colour of the icons beside it, square blocks as in the logo: it draws the
 *  mode in use with four bars - three tab heads over the
 *  session, or three columns - and the bars move from one picture to the other when the mode changes (globals.css
 *  `.mx-view-glyph`). The tooltip names where a click leads. */
export function ViewSwitch() {
  const t = useT()
  const tabs = useSessionsUI((s) => s.tabs)
  const label = tabs ? t('tabs.toZones') : t('tabs.toTabs')
  return (
    <Tooltip content={`${label} (Alt+T)`}>
      <button
        type="button"
        aria-label={label}
        onClick={() => useSessionsUI.getState().setTabs(!tabs)}
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="tabs-toggle"
        data-mode={tabs ? 'tabs' : 'zones'}
      >
        <span aria-hidden className="mx-view-glyph" data-kind={tabs ? 'tabs' : 'zones'}>
          <i />
          <i />
          <i />
          <i />
        </span>
      </button>
    </Tooltip>
  )
}

/** Phone: one button in the session's header shows or hides the chips of the open sessions (pressed = Tabs). */
export function TabsToggle() {
  const t = useT()
  const on = useSessionsUI((s) => s.tabs)
  return (
    <Tooltip content={t('tabs.tabsTip')}>
      <Button
        variant={on ? 'secondary' : 'ghost'}
        size="icon-sm"
        aria-pressed={on}
        aria-label={t('tabs.tabs')}
        onClick={() => useSessionsUI.getState().setTabs(!on)}
        className="pointer-coarse:size-10"
        data-testid="tabs-toggle"
      >
        <PanelTop />
      </Button>
    </Tooltip>
  )
}

/** Phone: the chips, given by the session layer to the session's header (shown under its app bar, above the title). */
export const MobileTabsSlot = React.createContext<React.ReactNode>(null)

/** The col shown after `dir` steps from the focused one (wraps around). */
export function stepCol(dir: -1 | 1): Col | null {
  const st = useSessionsUI.getState()
  if (st.cols.length < 2) return null
  const i = Math.max(0, st.cols.findIndex((c) => c.key === st.focused))
  return st.cols[(i + dir + st.cols.length) % st.cols.length]
}

/** Chips of the open sessions. `onPick` shows a col (desktop: focus; phone: its URL). */
export function TabsBar({ sessions, onPick, className, compact }: { sessions: Session[] | undefined; onPick: (c: Col) => void; className?: string; /** "Waiting": its number only. */ compact?: boolean }) {
  const t = useT()
  const cols = useSessionsUI((s) => s.cols)
  const focused = useSessionsUI((s) => s.focused)
  const byId = React.useMemo(() => new Map((sessions || []).map((s) => [s.id, s])), [sessions])
  const bar = React.useRef<HTMLDivElement>(null)
  const line = React.useRef<HTMLSpanElement>(null)
  useTabIndicator(bar, line, [focused, cols.map((c) => c.key).join(' ')])
  // the chip on screen stays visible in the bar
  React.useEffect(() => {
    bar.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
  }, [focused])

  const close = (c: Col) => {
    const st = useSessionsUI.getState()
    const wasShown = st.focused === c.key
    st.close(c.key)
    const next = useSessionsUI.getState().cols.find((x) => x.key === useSessionsUI.getState().focused)
    if (wasShown && next) onPick(next)
  }
  const waiting = cols.filter((c) => c.key !== focused && c.kind === 'session' && waits(byId.get(c.id)))

  if (!cols.length) return null
  return (
    <div className={cn('flex min-w-0 shrink-0 items-center gap-1 border-b bg-sidebar/40 px-2 py-1.5', className)} data-testid="tabs-bar">
      <div ref={bar} role="tablist" className="relative flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]">
        <span
          ref={line}
          aria-hidden
          className="pointer-events-none absolute bottom-0 left-0 h-0.5 w-[100px] origin-left bg-primary opacity-0 transition-[transform,opacity] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]"
        />
        {cols.map((c) => {
          const s = c.kind === 'session' ? byId.get(c.id) : undefined
          const on = c.key === focused
          const title = c.kind === 'new' ? `${t('sessions.newSession')} · ${topicLabel(c.path, t('sessions.root'))}` : (s?.title ?? '…')
          return (
            <div
              key={c.key}
              role="tab"
              aria-selected={on}
              className={cn(
                // computer: the chips share the bar with the page's actions - they narrow (down to 7rem) before the bar scrolls
                'group flex h-8 max-w-56 max-md:shrink-0 md:min-w-28 items-center gap-1.5 rounded-full border pr-1 pl-2.5 pointer-coarse:h-10 pointer-coarse:pr-0 text-[13px] transition-colors',
                on ? 'border-primary/50 bg-primary/10 text-foreground' : 'border-transparent bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
              data-tab={c.key}
            >
              <button type="button" className="flex min-w-0 items-center gap-1.5 outline-none pointer-coarse:self-stretch focus-visible:underline" onClick={() => onPick(c)} title={s ? topicLabel(s.path, t('sessions.root')) : undefined}>
                {s?.state === 'running' ? (
                  <StatusDot tone="running" pulse label={t('sessions.state.running')} />
                ) : s?.state === 'error' ? (
                  <StatusDot tone="error" label={t('sessions.state.error')} />
                ) : s?.unread ? (
                  <StatusDot tone="unread" label={t('sessions.unreadOne')} />
                ) : (
                  <StatusDot tone="idle" className="size-1.5" />
                )}
                <span className="min-w-0 truncate">
                  <Sensitive length={10}>{title}</Sensitive>
                </span>
              </button>
              <button
                type="button"
                aria-label={t('tabs.close')}
                onClick={() => close(c)}
                className={cn('flex size-6 shrink-0 items-center justify-center rounded-full text-muted-foreground pointer-coarse:size-10 hover:bg-foreground/10 hover:text-foreground', !on && 'md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100')}
              >
                <X className="size-3.5" />
              </button>
            </div>
          )
        })}
      </div>
      {waiting.length > 0 && (
        <Tooltip content={t('tabs.nextWaitingTip')}>
          <Button variant="ghost" size="sm" onClick={() => onPick(waiting[0])} className="shrink-0 gap-1.5 tabular-nums" data-testid="tabs-next-waiting">
            <StatusDot tone="unread" className="size-1.5" />
            {!compact && <span className="max-md:hidden">{t('tabs.nextWaiting')}</span>} {waiting.length}
          </Button>
        </Tooltip>
      )}
    </div>
  )
}

/** Computer: previous / next session, on the left and right edges of the session (faint until hovered). */
export function TabsArrows({ onPick }: { onPick: (c: Col) => void }) {
  const t = useT()
  const many = useSessionsUI((s) => s.cols.length > 1)
  if (!many) return null
  const step = (dir: -1 | 1) => {
    const c = stepCol(dir)
    if (c) onPick(c)
  }
  const cls =
    'absolute top-1/2 z-20 flex size-10 -translate-y-1/2 items-center justify-center rounded-full border bg-background/80 text-muted-foreground opacity-40 shadow-sm backdrop-blur transition-opacity hover:text-foreground hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
  return (
    <>
      <Tooltip content={`${t('sessions.shortcuts.prev')} (Alt+←)`} side="right">
        <button type="button" aria-label={t('sessions.shortcuts.prev')} onClick={() => step(-1)} className={cn(cls, 'left-2')} data-testid="tabs-prev">
          <ChevronLeft className="size-5" />
        </button>
      </Tooltip>
      <Tooltip content={`${t('sessions.shortcuts.next')} (Alt+→)`} side="left">
        <button type="button" aria-label={t('sessions.shortcuts.next')} onClick={() => step(1)} className={cn(cls, 'right-4')} data-testid="tabs-next">
          <ChevronRight className="size-5" />
        </button>
      </Tooltip>
    </>
  )
}

/** Phone: a sideways swipe on the session shows the previous / next one (not over something that scrolls sideways). */
export function useSwipe(ref: React.RefObject<HTMLElement | null>, on: boolean, go: (dir: -1 | 1) => void) {
  React.useEffect(() => {
    const el = ref.current
    if (!el || !on) return
    let start: { x: number; y: number; t: number } | null = null
    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return (start = null)
      for (let n = e.target as HTMLElement | null; n && n !== el; n = n.parentElement)
        if (n.scrollWidth > n.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return (start = null)
      if ((e.target as HTMLElement).closest('textarea, input, [contenteditable="true"]')) return (start = null)
      // Text being selected (to copy it): a flick moves the selection handles, it does not change the tab.
      if (document.getSelection()?.toString()) return (start = null)
      start = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() }
    }
    const onEnd = (e: TouchEvent) => {
      if (!start) return
      const dx = e.changedTouches[0].clientX - start.x
      const dy = e.changedTouches[0].clientY - start.y
      const fast = Date.now() - start.t < 600
      start = null
      if (document.getSelection()?.toString()) return
      if (fast && Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 2) go(dx < 0 ? 1 : -1)
    }
    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchend', onEnd, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchend', onEnd)
    }
  }, [ref, on, go])
}
