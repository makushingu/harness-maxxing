// Second column of the unfolded desktop sidebar: the Sessions page's own tree (filter, Running / Unread chips,
// folding, menus, archived folds), lazy-loaded from the Sessions page chunk the first time the bar unfolds (the
// shell stays in the core chunk). A pick opens the session (pages/sessions/RailTree.tsx) and folds the bar.
// Hovering a session row (mouse) or focusing it (keyboard) shows its preview card beside the rail: delegated on the
// tree's `data-session-row` buttons, so the tree itself knows nothing about it.
// The container (placement, width, slide) is the sidebar's: this component only fills it.
import * as React from 'react'
import { useSessions } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { useT, withGroups } from '@/i18n'
import { Skeleton } from '@/components/ui'
import { SessionPreviewCard } from './SessionPreview'

const RailTree = React.lazy(withGroups(['files'], () => import('@/pages/sessions/RailTree')))
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

export const sessionHref = (s: Session) => `/sessions?path=${encodeURIComponent(s.path)}&session=${encodeURIComponent(s.id)}`

const rowOf = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLElement>('[data-session-row]') : null)

export function SessionsRail({ onPick }: { onPick?: () => void }) {
  const t = useT()
  const railRef = React.useRef<HTMLDivElement>(null)
  const preview = usePreview()
  // The tree's own queries (same keys): the archived list is only read from the cache, the tree decides to load it.
  const { data: live } = useSessions()
  const { data: archived } = useSessions(undefined, true, false)
  const shownSession = preview.at ? (live?.find((s) => s.id === preview.at!.id) ?? archived?.find((s) => s.id === preview.at!.id)) : undefined
  const pick = React.useCallback(() => {
    preview.hide(0)
    onPick?.()
  }, [preview, onPick])

  const inRail = (t: EventTarget | null) => t instanceof Node && !!railRef.current?.contains(t)
  return (
    <div
      ref={railRef}
      // Pointer events of the card (a portal, React child of this div) bubble here too: only rows inside the rail count.
      onPointerOver={(e) => {
        if (e.pointerType !== 'mouse' || !inRail(e.target)) return
        const row = rowOf(e.target)
        if (row && canHover()) {
          if (preview.at?.el !== row) preview.show(row.dataset.sessionRow!, row, PREVIEW_DELAY_MS)
          else preview.keep()
        } else if (preview.at) preview.hide()
      }}
      onPointerLeave={(e) => e.pointerType !== 'touch' && preview.hide()}
      onFocus={(e) => {
        const row = inRail(e.target) ? rowOf(e.target) : null
        if (row && row.matches(':focus-visible')) preview.show(row.dataset.sessionRow!, row, 0)
      }}
      onBlur={(e) => rowOf(e.target) && preview.hide(0)}
      onClickCapture={(e) => rowOf(e.target) && preview.hide(0)}
      onScrollCapture={() => preview.at && preview.hide(0)}
      onContextMenuCapture={() => preview.hide(0)}
      className="flex h-full min-h-0 w-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
      data-testid="sessions-rail-body"
    >
      <React.Suspense fallback={<RailSkeleton />}>
        <RailTree onPick={pick} className="h-full min-h-0 flex-1" />
      </React.Suspense>
      {shownSession && preview.at && railRef.current && (
        <SessionPreviewCard
          session={shownSession}
          anchor={preview.at.el.closest<HTMLElement>('[role="treeitem"]') ?? preview.at.el}
          rail={railRef.current}
          root={t('sessions.root')}
          onPointerEnter={preview.keep}
          onPointerLeave={() => preview.hide()}
        />
      )}
    </div>
  )
}

function RailSkeleton() {
  return (
    <div className="grid gap-2 p-2" aria-hidden>
      <Skeleton className="h-8 w-full rounded-lg" />
      <Skeleton className="h-6 w-2/3 rounded-full" />
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-7 rounded-md" style={{ width: `${90 - ((i * 13) % 35)}%` }} />
      ))}
    </div>
  )
}
