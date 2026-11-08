// Second column of the unfolded desktop sidebar: the sessions within one click (running, unread, then the most
// recent), with a small filter. A row opens its session in the Sessions page strip the same way the command
// palette does (`/sessions?path=…&session=…`: the page's URL -> state effect calls `openSession`). The list is the
// live sessions query (refreshed by the event bus while it is mounted), no polling of its own.
// The container (placement, width, slide) is the sidebar's: this component only fills it.
import * as React from 'react'
import { Link } from 'react-router'
import { Clock, Search } from 'lucide-react'
import { useSessions } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import { Sensitive, StatusDot } from '@/components/ui'
import { SessionPreviewCard } from './SessionPreview'

const MAX_ROWS = 15
/** Hover intent before the preview card shows; once shown, another row switches it at once. */
const PREVIEW_DELAY_MS = 250
const PREVIEW_SWITCH_MS = 70
/** Grace to cross from a row to the card (or to the next row) before the card goes. */
const PREVIEW_CLOSE_MS = 140

const canHover = () => typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches

/** The preview card's state: which row, opened after a short hover intent (mouse) or at once (keyboard focus). */
function usePreview() {
  const [at, setAt] = React.useState<{ id: string; el: HTMLElement } | null>(null)
  const openTimer = React.useRef<number | undefined>(undefined)
  const closeTimer = React.useRef<number | undefined>(undefined)
  const shown = React.useRef(false)
  shown.current = at !== null
  const stop = () => {
    window.clearTimeout(openTimer.current)
    window.clearTimeout(closeTimer.current)
  }
  React.useEffect(() => stop, [])
  return React.useMemo(() => {
    const show = (id: string, el: HTMLElement, delay: number) => {
      window.clearTimeout(openTimer.current)
      window.clearTimeout(closeTimer.current)
      if (!delay) setAt({ id, el })
      // card already up: follow the pointer after a short beat (rows only crossed on the way are not loaded)
      else openTimer.current = window.setTimeout(() => setAt({ id, el }), shown.current ? PREVIEW_SWITCH_MS : delay)
    }
    const hide = (delay = PREVIEW_CLOSE_MS) => {
      stop()
      if (delay) closeTimer.current = window.setTimeout(() => setAt(null), delay)
      else setAt(null)
    }
    return { at, show, hide, keep: stop }
  }, [at])
}

/** "project / topic" of a session path (no import from the Sessions page: the shell stays in the core chunk). */
function whereOf(path: string, root: string): string {
  if (!path) return root
  const m = /^projects\/([^/]+)(?:\/topics\/([^/]+))?$/.exec(path)
  return m ? (m[2] ? `${m[1]} / ${m[2]}` : m[1]) : path
}

const fold = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

export const sessionHref = (s: Session) => `/sessions?path=${encodeURIComponent(s.path)}&session=${encodeURIComponent(s.id)}`

type Group = { key: 'running' | 'unread' | 'recent'; title: string; items: Session[] }

export function SessionsRail({ onPick }: { onPick?: () => void }) {
  const t = useT()
  const lang = useLang()
  const { data: sessions, isPending } = useSessions()
  const [q, setQ] = React.useState('')
  const listRef = React.useRef<HTMLDivElement>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const root = t('sessions.root')
  const railRef = React.useRef<HTMLDivElement>(null)
  const preview = usePreview()

  // Relative times stay true while the rail is open.
  const [, tick] = React.useReducer((n: number) => n + 1, 0)
  React.useEffect(() => {
    const id = window.setInterval(tick, 60_000)
    return () => window.clearInterval(id)
  }, [])

  const groups = React.useMemo<Group[]>(() => {
    const needle = fold(q.trim())
    const live = (sessions || []).filter((s) => !s.archived && (!needle || fold(`${s.title} ${whereOf(s.path, root)}`).includes(needle)))
    const byRecent = [...live].sort((a, b) => b.updated - a.updated)
    const running = byRecent.filter((s) => s.state === 'running')
    const unread = byRecent.filter((s) => s.state !== 'running' && s.unread)
    const recent = byRecent.filter((s) => s.state !== 'running' && !s.unread)
    let room = MAX_ROWS
    const take = (list: Session[]) => {
      const out = list.slice(0, Math.max(0, room))
      room -= out.length
      return out
    }
    return [
      { key: 'running' as const, title: t('sessions.filter.running'), items: take(running) },
      { key: 'unread' as const, title: t('sessions.filter.unread'), items: take(unread) },
      { key: 'recent' as const, title: t('sessions.recent.title'), items: take(recent) },
    ].filter((g) => g.items.length > 0)
  }, [sessions, q, root, t])

  const rows = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-rail-row]') || [])
  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return
    const all = rows()
    if (!all.length) return
    e.preventDefault()
    const at = all.indexOf(document.activeElement as HTMLElement)
    const next =
      e.key === 'Home' ? 0
      : e.key === 'End' ? all.length - 1
      : e.key === 'ArrowDown' ? Math.min(all.length - 1, at + 1)
      : at <= 0 ? -1 : at - 1
    if (next < 0) inputRef.current?.focus()
    else all[next].focus()
  }
  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      rows()[0]?.focus()
    } else if (e.key === 'Enter') {
      const first = rows()[0]
      if (first) {
        e.preventDefault()
        first.click()
      }
    } else if (e.key === 'Escape' && q) {
      e.stopPropagation()
      setQ('')
    }
  }

  const shownSession = preview.at ? groups.flatMap((g) => g.items).find((s) => s.id === preview.at!.id) : undefined
  let i = 0
  const empty = !isPending && groups.length === 0
  return (
    <div
      ref={railRef}
      onPointerLeave={(e) => e.pointerType !== 'touch' && preview.hide()}
      className="flex h-full min-h-0 w-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
      data-testid="sessions-rail"
    >
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 px-3">
        <h2 className="truncate text-sm font-semibold">{t('shell.openSessions')}</h2>
        <Link
          to="/sessions"
          onClick={() => onPick?.()}
          className="rounded px-1.5 py-0.5 text-xs text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t('sessions.filter.all')}
        </Link>
      </div>
      <div className="shrink-0 px-3 pb-2">
        <label className="relative block">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={inputRef}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onInputKey}
            placeholder={t('sessions.tree.filter')}
            aria-label={t('sessions.tree.filter')}
            className="h-8 w-full rounded-md border border-sidebar-border bg-background/60 pr-2 pl-7 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-search-cancel-button]:hidden"
            data-testid="sessions-rail-filter"
          />
        </label>
      </div>
      <div ref={listRef} onKeyDown={onListKey} onScroll={() => preview.at && preview.hide(0)} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3" role="navigation" aria-label={t('shell.openSessions')}>
        {empty && <p className="px-2 py-6 text-center text-xs text-muted-foreground">{q.trim() ? t('common.noResults') : t('shell.railEmpty')}</p>}
        {groups.map((g) => (
          <section key={g.key} aria-label={g.title} className="mt-1 first:mt-0">
            <h3 className="flex h-7 items-center px-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{g.title}</h3>
            <ul className="grid gap-px">
              {g.items.map((s) => {
                const n = i++
                return (
                  <li key={s.id}>
                    <Link
                      to={sessionHref(s)}
                      onClick={() => {
                        preview.hide(0)
                        onPick?.()
                      }}
                      onPointerEnter={(e) => e.pointerType === 'mouse' && canHover() && preview.show(s.id, e.currentTarget, PREVIEW_DELAY_MS)}
                      onPointerLeave={(e) => e.pointerType === 'mouse' && preview.hide()}
                      onFocus={(e) => e.currentTarget.matches(':focus-visible') && preview.show(s.id, e.currentTarget, 0)}
                      onBlur={() => preview.hide(0)}
                      data-rail-row={s.id}
                      style={{ animation: 'mx-label-in 120ms cubic-bezier(0.16, 1, 0.3, 1) backwards', animationDelay: `${Math.min(n, 10) * 12}ms` }}
                      className={cn(
                        'flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 outline-none transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
                        s.unread && 'font-medium',
                      )}
                    >
                      <span className="flex size-3.5 shrink-0 items-center justify-center">
                        {s.state === 'running' ? (
                          <StatusDot tone="running" pulse label={t('sessions.state.running')} />
                        ) : s.state === 'error' ? (
                          <StatusDot tone="error" label={t('sessions.state.error')} />
                        ) : s.unread ? (
                          <StatusDot tone="unread" label={t('sessions.unreadOne')} />
                        ) : s.source === 'cron' ? (
                          <Clock className="size-3 text-muted-foreground" aria-label={t('sessions.source.cron')} />
                        ) : (
                          <StatusDot tone="idle" className="size-1.5" />
                        )}
                      </span>
                      <span className="grid min-w-0 flex-1">
                        <span className="truncate text-[13px] leading-5">
                          <Sensitive length={10}>{s.title}</Sensitive>
                        </span>
                        <span className="flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
                          <span className="min-w-0 flex-1 truncate">
                            <Sensitive length={8}>{whereOf(s.path, root)}</Sensitive>
                          </span>
                          <span className="shrink-0 tabular-nums">{fmtRelative(s.updated, lang)}</span>
                        </span>
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
      {shownSession && preview.at && railRef.current && (
        <SessionPreviewCard
          session={shownSession}
          anchor={preview.at.el}
          rail={railRef.current}
          root={root}
          onPointerEnter={preview.keep}
          onPointerLeave={() => preview.hide()}
        />
      )}
    </div>
  )
}
