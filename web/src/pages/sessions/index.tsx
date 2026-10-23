// Sessions page — owns /sessions/*.
// URL contract: /sessions?path=<topic path>[&session=<id>][&new=1][&open=<id,id…>]
//   session → open (or focus) that session's column · new=1 → a "new session" column for `path`
//   (&prompt=<text>: typed in its composer, e.g. the dashboard's "Make it yours" examples)
//   path alone → reveal the topic in the tree · open → other open columns (shareable layout).
// /sessions/solo/<id> → one full-screen column (detached window) · /sessions/hud/<id> → HUD popup
// (browsers without Document Picture-in-Picture) · /sessions/<id> → redirect.
import * as React from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { Columns2, Keyboard, LayoutGrid, MessageSquarePlus, MessagesSquare, PanelLeftOpen } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { animateIn, animateOut, EASE_OUT, reducedMotion, usePresence } from '@/lib/presence'
import { useRegisterCommands } from '@/commands/registry'
import { useHotkey } from '@/commands/shortcuts'
import { useSessions, useSessionSeeded, useSettings, useWorkspace } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { PageHeader } from '@/components/shell/Page'
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, EmptyState, Kbd, MOD, Tooltip } from '@/components/ui'
import { focusComposer, prefillDraft, ROW_SPLIT_MAX, ROW_SPLIT_MIN, useSessionsUI, type Col } from './store'
import { SessionTree } from './Tree'
import { LayoutDropBar, LayoutPicker } from './LayoutPicker'
import { MIN_W, MAX_W, NewSessionColumn, SessionColumn, StripContext, type ColumnVariant, type Place } from './Column'
import { PreviewProvider } from './FilePreview'
import { HudBar } from './Hud'
import { topicLabel, useIsMobile } from './util'
import { useTouchNav } from '@/components/shell/TouchNav'
import { enter, MaxxingDriver, promoteColumn, useMaxxing, useMaxxingEnabled } from './maxxing'
import { MaxxingControls } from './MaxxingMeter'

/** Sessions sliding to their new place (reorder, stack, layout): short, the content is heavy. */
const FLIP_MS = 180

export default function SessionsPage() {
  return (
    <PreviewProvider>
      <Routes>
        <Route path="solo/:id" element={<SoloView />} />
        <Route path="hud/:id" element={<HudView />} />
        <Route path=":id" element={<RedirectToSession />} />
        <Route index element={<Workspace />} />
      </Routes>
    </PreviewProvider>
  )
}

function RedirectToSession() {
  const { id } = useParams()
  return <Navigate to={`/sessions?session=${encodeURIComponent(id || '')}`} replace />
}

/* ---------------------------------------------------------------- main view */
function Workspace() {
  const t = useT()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const mobile = useIsMobile()
  // Narrow subscriptions: the page re-renders when its columns change, not on every store write (tree folds,
  // sort, widths saved while resizing...).
  const cols = useSessionsUI((s) => s.cols)
  const focused = useSessionsUI((s) => s.focused)
  const treeHidden = useSessionsUI((s) => s.treeHidden)
  const widths = useSessionsUI((s) => s.widths)
  const rowSplit = useSessionsUI((s) => s.rowSplit)
  const setTreeHidden = useSessionsUI((s) => s.setTreeHidden)
  const { data: ws } = useWorkspace()
  const { data: sessions, isError: sessionsFailed, refetch: refetchSessions } = useSessions(undefined, false)
  const [helpOpen, setHelpOpen] = React.useState(false)

  const focusedCol = cols.find((c) => c.key === focused) || null
  const focusedId = focusedCol?.kind === 'session' ? focusedCol.id : null
  const { data: focusedSession } = useSessionSeeded(focusedId)
  const paramPath = params.get('path')
  const currentTopic = focusedCol?.kind === 'new' ? focusedCol.path : (focusedSession?.path ?? paramPath)

  // new=1&prompt=<text>: put the text in the new column's draft before the composer mounts (read at its first render).
  // The URL is rewritten without it right after, so a reload does not type it again.
  React.useMemo(() => {
    const prompt = params.get('prompt')
    const path = params.get('path')
    if (!prompt || params.get('new') !== '1' || path === null) return
    prefillDraft(`new:${path}`, prompt)
  }, [location.search]) // eslint-disable-line react-hooks/exhaustive-deps

  // URL → state (intents). Idempotent: re-running on our own URL writes is a no-op.
  React.useEffect(() => {
    const st = useSessionsUI.getState()
    const sid = params.get('session')
    const path = params.get('path')
    for (const id of (params.get('open') || '').split(',').filter(Boolean)) st.openSession(id, { focus: false })
    if (sid) st.openSession(sid)
    // A badge was clicked: the tree shows those sessions (and comes back if it was folded away).
    const show = params.get('show')
    if (show === 'running' || show === 'unread') {
      st.setShow(show)
      if (st.treeHidden) st.setTreeHidden(false)
      if (mobile) useTouchNav.getState().setPanel('sessions')
    }
    else if (params.get('new') === '1' && path !== null) {
      const f = st.cols.find((c) => c.key === st.focused)
      if (!(f?.kind === 'new' && f.path === path)) st.openNew(path)
    }
    if (path) {
      // Reveal the topic in the tree.
      const project = /^projects\/([^/]+)/.exec(path)?.[1]
      if (project && st.expanded[`p:${project}`] === false) st.toggle(`p:${project}`, true)
      if (!st.expanded[`t:${path}`]) st.toggle(`t:${path}`, true)
    }
  }, [location.search]) // eslint-disable-line react-hooks/exhaustive-deps

  // State → URL (desktop): the focused column + the other open sessions, replace-only.
  React.useEffect(() => {
    if (mobile) return
    const next = new URLSearchParams()
    if (focusedCol?.kind === 'session') {
      const p = focusedSession?.path ?? paramPath
      if (p !== null && p !== undefined) next.set('path', p)
      next.set('session', focusedCol.id)
    } else if (focusedCol?.kind === 'new') {
      next.set('path', focusedCol.path)
      next.set('new', '1')
    } else if (paramPath) next.set('path', paramPath)
    const others = cols.filter((c): c is Extract<Col, { kind: 'session' }> => c.kind === 'session' && c.key !== focused).map((c) => c.id)
    if (others.length) next.set('open', others.join(','))
    const s = next.toString()
    if (s !== params.toString()) navigate({ search: s ? `?${s}` : '' }, { replace: true })
  }, [mobile, focusedCol, focusedSession?.path, cols]) // eslint-disable-line react-hooks/exhaustive-deps

  const mobileOpen = mobile && (!!params.get('session') || params.get('new') === '1') && !!focusedCol

  // Touch layout, no session asked: blank (background) until the redirect below picks one (or the asked one is set up) - no list or header flash.
  // Not when the list failed to load: the header and a retry stay reachable.
  const asked = !!params.get('session') || params.get('new') === '1'
  const touchPicking = mobile && !mobileOpen && !(sessionsFailed && !sessions) && (asked || !sessions || sessions.length > 0)
  // Touch layout: /sessions always shows a session, full screen - the one on screen last time, else the most recent.
  // The list lives in the sessions drawer (☰).
  React.useEffect(() => {
    if (!mobile || params.get('session') || params.get('new') === '1' || !sessions) return
    const f = useSessionsUI.getState().cols.find((c) => c.key === useSessionsUI.getState().focused)
    const show = params.get('show')
    const keep = show ? `&show=${show}` : ''
    if (f?.kind === 'new') {
      navigate(`/sessions?path=${encodeURIComponent(f.path)}&new=1${keep}`, { replace: true })
      return
    }
    const last = (f?.kind === 'session' && sessions.find((s) => s.id === f.id)) || [...sessions].sort((a, b) => b.updated - a.updated)[0]
    if (last) navigate(`/sessions?path=${encodeURIComponent(last.path)}&session=${last.id}${keep}`, { replace: true })
  }, [mobile, location.search, !!sessions]) // eslint-disable-line react-hooks/exhaustive-deps

  const openSession = React.useCallback(
    (s: Pick<Session, 'id' | 'path'>) => {
      if (mobile) {
        navigate(`/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`, { state: { mxPushed: true } })
        return
      }
      const key = useSessionsUI.getState().openSession(s.id)
      requestAnimationFrame(() => {
        document.querySelector(`[data-col="${key}"]`)?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
        focusComposer(key)
      })
    },
    [mobile, navigate],
  )
  const newSession = React.useCallback(
    (path: string) => {
      if (mobile) {
        navigate(`/sessions?path=${encodeURIComponent(path)}&new=1`, { state: { mxPushed: true } })
        return
      }
      const key = useSessionsUI.getState().openNew(path)
      requestAnimationFrame(() => {
        document.querySelector(`[data-col="${key}"]`)?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
        focusComposer(key)
      })
    },
    [mobile, navigate],
  )

  // Maxxing mode (beta, Settings -> Features): a finished session comes to the front (first, big column; full screen
  // on a phone). Turned off in the settings while on in this browser: it ends, the previous arrangement comes back.
  const maxxingEnabled = useMaxxingEnabled()
  const { isSuccess: settingsLoaded } = useSettings()
  React.useEffect(() => {
    if (settingsLoaded && !maxxingEnabled && useMaxxing.getState().on) useMaxxing.getState().setOn(false)
  }, [settingsLoaded, maxxingEnabled])
  const showMaxxing = React.useCallback(
    (s: Session) => {
      if (mobile) {
        navigate(`/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`, { state: { mxPushed: true } })
        requestAnimationFrame(() => requestAnimationFrame(() => enter(document.querySelector('[data-touch-layer] > *'))))
      } else promoteColumn(s.id, strip.current)
    },
    [mobile, navigate],
  )

  const topics = React.useMemo(() => (ws?.projects || []).flatMap((p) => p.topics), [ws])
  const defaultTopic = currentTopic ?? topics[0]?.path ?? null
  const newInCurrent = () => defaultTopic !== null && newSession(defaultTopic)

  // Keyboard: Alt+N / Alt+←→ / Alt+W / Alt+M (Maxxing mode) use e.code (layout- and macOS-proof), '/' focuses the composer.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.defaultPrevented) return
      const st = useSessionsUI.getState()
      const i = st.cols.findIndex((c) => c.key === st.focused)
      if (e.code === 'KeyN') {
        e.preventDefault()
        newInCurrent()
      } else if ((e.code === 'ArrowLeft' || e.code === 'ArrowRight') && st.cols.length) {
        e.preventDefault()
        const j = Math.max(0, Math.min(st.cols.length - 1, (i < 0 ? 0 : i) + (e.code === 'ArrowLeft' ? -1 : 1)))
        st.focus(st.cols[j].key)
        focusComposer(st.cols[j].key)
      } else if (e.code === 'KeyM' && maxxingEnabled) {
        e.preventDefault()
        useMaxxing.getState().setOn(!useMaxxing.getState().on)
      } else if (e.code === 'KeyW' && st.focused) {
        e.preventDefault()
        st.close(st.focused)
        const nf = useSessionsUI.getState().focused
        requestAnimationFrame(() => focusComposer(nf))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  useHotkey('/', () => focusComposer(useSessionsUI.getState().focused || useSessionsUI.getState().cols[0]?.key || null))

  // ⌘K palette: search, new session here, recent sessions.
  const recent = (sessions || []).slice(0, 8)
  useRegisterCommands(
    'sessions',
    [
      ...(defaultTopic !== null
        ? [
            {
              id: 'sessions:new-here',
              title: `${t('palette.newSessionIn')} ${topicLabel(defaultTopic, t('sessions.root'))}`,
              group: t('nav.sessions'),
              icon: MessageSquarePlus,
              sensitive: true,
              shortcut: ['Alt', 'N'],
              perform: () => newInCurrent(),
            },
          ]
        : []),
      ...recent.map((s) => ({
        id: `sessions:recent:${s.id}`,
        title: s.title,
        hint: topicLabel(s.path, t('sessions.root')),
        group: t('sessions.recent'),
        icon: MessagesSquare,
        sensitive: true,
        perform: () => openSession(s),
      })),
      { id: 'sessions:shortcuts', title: t('sessions.shortcuts.title'), group: t('nav.sessions'), icon: Keyboard, perform: () => setHelpOpen(true) },
    ],
    [t, defaultTopic, recent.map((s) => s.id + s.title).join('|'), mobile],
  )

  // Columns open (grow from the right), close (shrink while the others slide over) and move (slide) smoothly.
  // The strip is a CSS grid: every session is a direct child (stacking never remounts a thread); `below` puts a
  // session under the one before it, in the same column of the grid (2x2).
  const shownCols = usePresence(cols, (c) => c.key)
  // The panes stay in the DOM in the order they were opened: their place on screen comes from the grid
  // (gridColumn / gridRow), and moving a node in the DOM resets its scroll - a moved session jumped to the top
  // of its conversation.
  const domOrder = React.useRef<string[]>([])
  const domCols = React.useMemo(() => {
    const byKey = new Map(shownCols.map((p) => [p.key, p]))
    const keys = domOrder.current.filter((k) => byKey.has(k))
    for (const p of shownCols) if (!keys.includes(p.key)) keys.push(p.key)
    domOrder.current = keys
    return keys.map((k) => byKey.get(k)!)
  }, [shownCols])
  const strip = React.useRef<HTMLDivElement>(null)
  // Mouse: the wheel over the strip but on no session (gap, empty cell, edge) scrolls it sideways.
  // Trackpad: a sideways swipe anywhere over the columns scrolls the strip. The threads inside contain their
  // overscroll (vertical lists), which swallowed horizontal wheel deltas unless the pointer sat below them.
  // The strip snaps to columns: a programmatic scroll of a few pixels is snapped straight back, so snapping is
  // off while the fingers move and comes back right after (the strip then settles on the nearest column).
  // Listening on the document (not the strip) keeps working whenever the strip is mounted or re-mounted.
  React.useEffect(() => {
    if (mobile) return
    let settle = 0
    const onWheel = (e: WheelEvent) => {
      const el = strip.current
      if (!el || !(e.target instanceof Node) || !el.contains(e.target)) return
      if (e.ctrlKey || el.scrollWidth <= el.clientWidth) return
      // Mouse wheel (a pointer that hovers) over the strip but on no session: the wheel scrolls the strip sideways.
      const offColumn = e.target instanceof Element && !e.target.closest('[data-col]')
      const wheelSideways = offColumn && Math.abs(e.deltaY) > Math.abs(e.deltaX) && window.matchMedia('(hover: hover) and (pointer: fine)').matches
      if (!wheelSideways && Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return
      const delta = wheelSideways ? e.deltaY : e.deltaX
      // leave it to an inner element that can still scroll sideways (code blocks, tables, tab bars)
      for (let n = e.target as HTMLElement | null; n && n !== el; n = n.parentElement) {
        if (n.scrollWidth > n.clientWidth) {
          const ox = getComputedStyle(n).overflowX
          if ((ox === 'auto' || ox === 'scroll') && (delta < 0 ? n.scrollLeft > 0 : n.scrollLeft + n.clientWidth < n.scrollWidth - 1)) return
        }
      }
      e.preventDefault()
      stopGlide()
      el.style.scrollSnapType = 'none'
      el.scrollLeft += e.deltaMode === 1 ? delta * 16 : delta
      window.clearTimeout(settle)
      settle = window.setTimeout(() => glideToColumn(el), 180)
    }
    // Turning snapping back on made the browser jump to the column: glide there first, then turn it back on
    // (it is already in place). Like `snap-proximity`, only when a column edge is near.
    let stopGlide = () => {}
    const glideToColumn = (el: HTMLDivElement) => {
      const max = el.scrollWidth - el.clientWidth
      let target: number | null = null
      for (const c of el.querySelectorAll<HTMLElement>(':scope > [data-col]')) {
        const left = Math.min(max, Math.max(0, c.offsetLeft))
        if (target == null || Math.abs(left - el.scrollLeft) < Math.abs(target - el.scrollLeft)) target = left
      }
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      if (target == null || reduce || Math.abs(target - el.scrollLeft) < 1 || Math.abs(target - el.scrollLeft) > el.clientWidth * 0.3) {
        el.style.scrollSnapType = ''
        return
      }
      const done = () => {
        stopGlide()
        el.style.scrollSnapType = ''
      }
      const fallback = window.setTimeout(done, 700)
      el.addEventListener('scrollend', done, { once: true })
      stopGlide = () => {
        window.clearTimeout(fallback)
        el.removeEventListener('scrollend', done)
        stopGlide = () => {}
      }
      el.scrollTo({ left: target, behavior: 'smooth' })
    }
    document.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      document.removeEventListener('wheel', onWheel)
      window.clearTimeout(settle)
      stopGlide()
    }
  }, [mobile])
  const colEl = (k: string) => strip.current?.querySelector<HTMLElement>(`:scope > [data-col="${CSS.escape(k)}"]`) ?? null
  const places = React.useMemo(() => {
    const out = new Map<string, Place>()
    const tops: string[] = []
    let prev: { key: string; place: Place } | null = null
    for (const p of shownCols) {
      if (p.item.below && prev && prev.place.row === 'full') {
        prev.place.row = 'top'
        out.set(p.key, { col: prev.place.col, row: 'bottom', top: prev.key })
        prev = null
        continue
      }
      const place: Place = { col: tops.length + 1, row: 'full' }
      tops.push(p.key)
      out.set(p.key, place)
      prev = { key: p.key, place }
    }
    return { places: out, tops }
  }, [shownCols])
  const wide = React.useMemo(() => new Set(cols.filter((c) => c.wide).map((c) => c.key)), [cols])
  const template = React.useCallback(
    (override?: { key: string; w: number }) =>
      places.tops
        .map((k) => {
          const w = override?.key === k ? override.w : places.tops.length > 1 ? widths[k] : undefined
          // a resized column keeps its width while there is room, then shrinks to MIN_W before the strip scrolls
          if (w) return `minmax(${MIN_W}px, ${Math.round(w)}px)`
          return `minmax(${MIN_W}px, ${places.tops.length > 1 && wide.has(k) ? 2 : 1}fr)`
        })
        .join(' '),
    [places, widths, wide],
  )
  const rows = (r: number) => `minmax(120px, ${r}fr) minmax(120px, ${1 - r}fr)`
  const stacked = cols.some((c) => c.below)

  React.useLayoutEffect(() => {
    for (const p of shownCols) {
      const el = colEl(p.key)
      if (!el) continue
      if (p.leaving && !el.dataset.leaving) {
        el.dataset.leaving = '1'
        animateOut(el, 'x')
      } else if (p.appear && !p.leaving && !el.dataset.appeared) {
        el.dataset.appeared = '1'
        animateIn(el, places.places.get(p.key)?.row === 'bottom' ? 'y' : 'x')
      }
    }
  })
  // FLIP in both directions: a session that moved (reorder, stacked, unstacked, a neighbour closed) slides from
  // where it was to its new cell.
  const lastRects = React.useRef(new Map<string, DOMRect>())
  const flips = React.useRef(new Map<string, Animation>())
  React.useLayoutEffect(() => {
    // a slide still running would skew the measures: it stops where the session really is
    for (const a of flips.current.values()) a.cancel()
    flips.current.clear()
    const now = new Map<string, DOMRect>()
    for (const p of shownCols) {
      if (p.leaving) continue
      const el = colEl(p.key)
      if (el) now.set(p.key, el.getBoundingClientRect())
    }
    if (!reducedMotion())
      for (const [k, r] of now) {
        const b = lastRects.current.get(k)
        if (!b) continue
        const dx = b.left - r.left
        const dy = b.top - r.top
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(b.height - r.height) < 2) continue
        // (a session whose height changed - stacked / unstacked - also dims briefly: scaling would squash its text)
        const a = colEl(k)?.animate([{ transform: `translate(${dx}px, ${dy}px)`, opacity: Math.abs(b.height - r.height) > 2 ? 0.75 : 1 }, { transform: 'none', opacity: 1 }], {
          duration: FLIP_MS,
          easing: EASE_OUT,
        })
        if (a) {
          flips.current.set(k, a)
          a.onfinish = () => flips.current.get(k) === a && flips.current.delete(k)
        }
      }
    lastRects.current = now
  }, [cols.map((c) => c.key + (c.below ? 'v' : '') + (c.wide ? 'w' : '') + (widths[c.key] ?? '')).join(' ')]) // eslint-disable-line react-hooks/exhaustive-deps

  // Resizing: the column handle (width of a grid column) and the row handle (height split of stacked sessions) set
  // the grid template live, then save it.
  const strip_ = React.useMemo(
    () => ({
      startColResize: (key: string, e: React.PointerEvent) => {
        const el = colEl(key)
        const st = strip.current
        if (!el || !st) return
        // (the bottom session's handle resizes the same grid column: its width is saved under the top key)
        e.preventDefault()
        const startX = e.clientX
        const startW = el.getBoundingClientRect().width
        const target = e.currentTarget as HTMLElement
        target.setPointerCapture(e.pointerId)
        let w = startW
        const onMove = (ev: PointerEvent) => {
          w = Math.max(MIN_W, Math.min(MAX_W, startW + ev.clientX - startX))
          st.style.gridTemplateColumns = template({ key, w })
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          useSessionsUI.getState().setWidth(key, w)
        }
        document.body.style.cursor = 'col-resize'
        target.addEventListener('pointermove', onMove)
        target.addEventListener('pointerup', onUp)
        target.addEventListener('pointercancel', onUp)
      },
      resetColWidth: (key: string) => useSessionsUI.getState().setWidth(key, null),
      startRowResize: (e: React.PointerEvent) => {
        const st = strip.current
        if (!st) return
        e.preventDefault()
        const box = st.getBoundingClientRect()
        const target = e.currentTarget as HTMLElement
        target.setPointerCapture(e.pointerId)
        let r = useSessionsUI.getState().rowSplit
        const onMove = (ev: PointerEvent) => {
          r = Math.max(ROW_SPLIT_MIN, Math.min(ROW_SPLIT_MAX, (ev.clientY - box.top) / box.height))
          st.style.gridTemplateRows = rows(r)
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          useSessionsUI.getState().setRowSplit(r)
        }
        document.body.style.cursor = 'row-resize'
        target.addEventListener('pointermove', onMove)
        target.addEventListener('pointerup', onUp)
        target.addEventListener('pointercancel', onUp)
      },
      resetRowSplit: () => useSessionsUI.getState().setRowSplit(0.5),
      columns: places.tops.length,
    }),
    [template, places.tops.length], // eslint-disable-line react-hooks/exhaustive-deps
  )

  const openIds = React.useMemo(() => new Set(cols.flatMap((c) => (c.kind === 'session' ? [c.id] : []))), [cols])

  const header = (
    <PageHeader
      title={t('nav.sessions')}
      description={t('sessions.description')}
      actions={
        <>
          {!mobile && cols.length >= 2 && (
            <LayoutPicker count={cols.length}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={stacked ? t('sessions.grid.off') : t('sessions.grid.on')}
                aria-pressed={stacked}
                onClick={() => (stacked ? useSessionsUI.getState().toColumns() : useSessionsUI.getState().toGrid())}
                data-testid="sessions-grid"
              >
                {stacked ? <Columns2 /> : <LayoutGrid />}
              </Button>
            </LayoutPicker>
          )}
          {maxxingEnabled && <MaxxingControls />}
          <Tooltip content={`${t('sessions.newSession')} (Alt+N)`}>
            <Button size={mobile ? 'icon' : 'sm'} onClick={newInCurrent} disabled={defaultTopic === null} aria-label={t('sessions.newSession')} data-tour="new-session">
              <MessageSquarePlus /> <span className="max-md:hidden">{t('sessions.newSession')}</span>
            </Button>
          </Tooltip>
        </>
      }
    />
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {maxxingEnabled && <MaxxingDriver sessions={sessions} show={showMaxxing} />}
      {/* Touch layout: the session layer has its own header (☰, ⋯, ⊞); nothing while the session to show is picked. */}
      {!mobileOpen && !touchPicking && header}
      <div className="flex min-h-0 flex-1">
        {!mobile && treeHidden && (
          // Folded tree: a slim rail keeps the unfold button where the fold button was (top left of the pane).
          <div className="flex w-11 shrink-0 flex-col items-center gap-1 border-r bg-sidebar/40 py-2">
            <Tooltip content={t('sessions.tree.show')} side="right">
              <Button variant="ghost" size="icon-sm" aria-label={t('sessions.tree.show')} onClick={() => setTreeHidden(false)}>
                <PanelLeftOpen />
              </Button>
            </Tooltip>
          </div>
        )}
        {mobile && !mobileOpen && !touchPicking && (
          <div className="flex flex-1 items-center justify-center p-6">
            {!sessions && sessionsFailed && (
              <EmptyState
                tone="error"
                icon={MessagesSquare}
                title={t('sessions.touch.loadError')}
                action={
                  <Button variant="outline" onClick={() => refetchSessions()}>
                    {t('common.retry')}
                  </Button>
                }
              />
            )}
            {sessions && (
              <EmptyState
                icon={MessagesSquare}
                title={t('sessions.touch.emptyTitle')}
                description={t('sessions.touch.emptyDesc')}
                action={
                  <>
                    <Button onClick={newInCurrent} disabled={defaultTopic === null}>
                      <MessageSquarePlus /> {t('sessions.newSession')}
                    </Button>
                    <Button variant="outline" onClick={() => useTouchNav.getState().setPanel('sessions')}>
                      <MessagesSquare /> {t('sessions.touch.list')}
                    </Button>
                  </>
                }
              />
            )}
          </div>
        )}
        {!mobile && !treeHidden && (
          <SessionTree
            onHide={() => setTreeHidden(true)}
            className="w-72 shrink-0 border-r bg-sidebar/40"
            onOpenSession={openSession}
            onNewSession={newSession}
            activePath={currentTopic ?? null}
            openIds={openIds}
            focusedId={focusedId}
          />
        )}
        {!mobile && (
          <StripContext.Provider value={strip_}>
          <div className="relative flex min-w-0 flex-1">
          <LayoutDropBar />
          <div
            ref={strip}
            className={cn('relative min-w-0 flex-1 pr-2 snap-x snap-proximity overflow-x-auto overflow-y-hidden', shownCols.length ? 'grid' : 'flex')}
            style={shownCols.length ? { gridTemplateColumns: template(), gridTemplateRows: rows(rowSplit) } : undefined}
            data-columns
          >
            {shownCols.length === 0 ? (
              <div className="flex flex-1 items-center justify-center">
                <EmptyState
                  icon={MessagesSquare}
                  title={t('sessions.empty.title')}
                  description={t('sessions.empty.desc')}
                  action={
                    <>
                      <Button onClick={newInCurrent} disabled={defaultTopic === null}>
                        <MessageSquarePlus /> {t('sessions.newSession')}
                      </Button>
                      <Button variant="outline" onClick={() => setHelpOpen(true)}>
                        <Keyboard /> {t('sessions.shortcuts.title')}
                      </Button>
                    </>
                  }
                />
              </div>
            ) : (
              domCols.map((p) => <ColumnFor key={p.key} col={p.item} index={Math.max(0, cols.indexOf(p.item))} count={cols.length} variant="column" place={places.places.get(p.key)} />)
            )}
          </div>
          </div>
          </StripContext.Provider>
        )}
      </div>
      {mobileOpen && focusedCol && <MobileOverlay col={focusedCol} />}
      <ShortcutsHelp open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}

// Memo: the page re-renders when the focus moves (tree highlight, URL); a column only when its own props change -
// each column follows its own focus state.
const ColumnFor = React.memo(function ColumnFor({ col, index, count, variant, place }: { col: Col; index: number; count: number; variant: ColumnVariant; place?: Place }) {
  if (col.kind === 'new') return <NewSessionColumn col={col} index={index} count={count} variant={variant} place={place} />
  return <SessionColumn key={col.id} col={col} sid={col.id} index={index} count={count} variant={variant} place={place} />
})

/** Touch layout: the session is a full-screen layer, sized to the visual viewport so the composer stays pinned right
 *  above the on-screen keyboard. Its header opens the sessions (☰) and the app menu (⊞). */
function MobileOverlay({ col }: { col: Col }) {
  const ref = React.useRef<HTMLDivElement>(null)
  React.useLayoutEffect(() => {
    const vv = window.visualViewport
    const el = ref.current
    if (!vv || !el) return
    // at most one write per frame (the keyboard fires many resize / scroll events while it moves)
    let frame = 0
    const write = () => {
      frame = 0
      el.style.height = `${vv.height}px`
      el.style.transform = `translateY(${vv.offsetTop}px)`
    }
    const apply = () => {
      if (!frame) frame = requestAnimationFrame(write)
    }
    write()
    vv.addEventListener('resize', apply)
    vv.addEventListener('scroll', apply)
    return () => {
      cancelAnimationFrame(frame)
      vv.removeEventListener('resize', apply)
      vv.removeEventListener('scroll', apply)
    }
  }, [])
  React.useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])
  return (
    <div ref={ref} className="fixed inset-0 z-[45] flex flex-col bg-background pr-[var(--safe-right)] pl-[var(--safe-left)]" data-touch-layer data-testid="touch-session">
      <ColumnFor col={col} index={0} count={1} variant="mobile" />
    </div>
  )
}

/* ---------------------------------------------------------------- detached window */
function SoloView() {
  const { id = '' } = useParams()
  const col = React.useMemo<Col>(() => ({ key: `solo:${id}`, kind: 'session', id }), [id])
  return (
    <div className="fixed inset-0 z-[45] flex flex-col bg-background">
      <SessionColumn key={id} col={col} sid={id} index={0} count={1} variant="solo" />
    </div>
  )
}

/* ---------------------------------------------------------------- HUD popup (browsers without Document PiP) */
function HudView() {
  const { id = '' } = useParams()
  const opener = window.opener as Window | null
  // A route of the app shown in the window that opened the HUD (its router follows popstate).
  const go = React.useCallback(
    (path: string) => {
      try {
        if (opener && !opener.closed) {
          opener.history.pushState(null, '', path)
          opener.dispatchEvent(new PopStateEvent('popstate'))
          opener.focus()
          return
        }
      } catch {
        /* opener gone or not reachable */
      }
      window.open(path, '_blank')
    },
    [opener],
  )
  return (
    <div className="fixed inset-0 z-[45]">
      <HudBar key={id} sid={id} win={window} onOpen={go} onOpenApp={opener ? () => opener.focus() : undefined} />
    </div>
  )
}

/* ---------------------------------------------------------------- shortcuts help */
function ShortcutsHelp({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const maxxing = useMaxxingEnabled()
  const rows: [string[], string][] = [
    [['Enter'], t('sessions.shortcuts.send')],
    [['Shift', 'Enter'], t('sessions.shortcuts.newline')],
    [[MOD, 'Enter'], t('sessions.shortcuts.send')],
    [['Esc'], t('sessions.shortcuts.blur')],
    [['/'], t('sessions.shortcuts.focus')],
    [['Alt', 'N'], t('sessions.shortcuts.new')],
    [['Alt', '←'], t('sessions.shortcuts.prev')],
    [['Alt', '→'], t('sessions.shortcuts.next')],
    [['Alt', 'W'], t('sessions.shortcuts.close')],
    ...(maxxing ? [[['Alt', 'M'], t('maxxing.toggle')] as [string[], string]] : []),
    [[MOD, 'K'], t('sessions.shortcuts.palette')],
  ]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('sessions.shortcuts.title')}</DialogTitle>
          <DialogDescription>{t('sessions.shortcuts.desc')}</DialogDescription>
        </DialogHeader>
        <ul className="grid gap-1.5">
          {rows.map(([keys, label], i) => (
            <li key={i} className="flex items-center justify-between gap-3 text-sm">
              <span>{label}</span>
              <span className="flex gap-1">
                {keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
