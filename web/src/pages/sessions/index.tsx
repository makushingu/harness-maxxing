// Sessions page — owns /sessions/*.
// URL contract: /sessions?path=<topic path>[&session=<id>][&new=1][&open=<id,id…>]
//   session → open (or focus) that session's column · new=1 → a "new session" column for `path`
//   (&prompt=<text>: typed in its composer, e.g. the dashboard's "Make it yours" examples)
//   path alone → reveal the topic in the tree · open → other open columns (shareable layout).
// /sessions/solo/<id> → one full-screen column (detached window) · /sessions/hud/<id> → HUD popup
// (browsers without Document Picture-in-Picture) · /sessions/<id> → redirect.
import * as React from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { Columns2, FolderOpen, Hash, Keyboard, LayoutGrid, MessageSquarePlus, MessagesSquare, PanelLeftOpen } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { animateIn, animateOut, EASE_OUT, reducedMotion, usePresence } from '@/lib/presence'
import { useTabSwitchMotion } from './tabMotion'
import { useOpenSync } from './openSync'
import { useRegisterCommands } from '@/commands/registry'
import { useHotkey } from '@/commands/shortcuts'
import { agentRunRoute, isAgentSession, useSessions, useSessionSeeded, useSettings, useWorkspace } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { PageHeader } from '@/components/shell/Page'
import { Button, Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, EmptyState, Kbd, MOD, Tooltip } from '@/components/ui'
import { focusComposer, MAX_STACK, prefillDraft, ROW_SPLIT_MAX, ROW_SPLIT_MIN, useSessionsUI, type Col } from './store'
import { stripRows } from './layouts'
import { SessionTree } from './Tree'
import { AgentHover } from '@/features/agents/AgentHover'
import { LayoutDropBar, LayoutPicker } from './LayoutPicker'
import { MIN_W, MAX_W, NewSessionColumn, SessionColumn, WhereBadge, StripContext, type ColumnVariant, type Place } from './Column'
import { PreviewProvider } from './FilePreview'
import { HudBar } from './Hud'
import { parseAgentPath, topicLabel, useIsMobile } from './util'
import { useTouchNav } from '@/components/shell/TouchNav'
import { PageList } from '@/components/shell/PageList'
import { useUI } from '@/stores/ui'
import { enter, MaxxingDriver, promoteColumn, useMaxxing, useMaxxingEnabled } from './maxxing'
import { MaxxingControls } from './MaxxingMeter'
import { MobileTabsSlot, stepCol, TabsArrows, TabsBar, TabsToggle, useSwipe } from './Tabs'

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
  const widths = useSessionsUI((s) => s.widths)
  const rowSplit = useSessionsUI((s) => s.rowSplit)
  const listOpen = useUI((s) => s.secondBarOpen)
  const setListOpen = useUI((s) => s.setSecondBarOpen)
  const tabs = useSessionsUI((s) => s.tabs)
  const { data: ws } = useWorkspace()
  const { data: sessions, isError: sessionsFailed, refetch: refetchSessions } = useSessions(undefined, false)
  const [helpOpen, setHelpOpen] = React.useState(false)
  const [listQuery, setListQuery] = React.useState('')

  // the open sessions are the same on the user's other devices
  useOpenSync(mobile)

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

  // A run of an agent (a link from Telegram, a notification, the feed, search) opens on the Agents page, not here.
  const askedSid = params.get('session')
  const { data: askedSession } = useSessionSeeded(askedSid)
  const agentRun = askedSid ? (parseAgentPath(paramPath) ? paramPath : askedSession && isAgentSession(askedSession) ? askedSession.path : null) : null
  React.useEffect(() => {
    if (!askedSid || !agentRun) return
    const st = useSessionsUI.getState()
    const col = st.cols.find((c) => c.kind === 'session' && c.id === askedSid)
    if (col) st.close(col.key)
    navigate(agentRunRoute(agentRun, askedSid), { replace: true })
  }, [askedSid, agentRun]) // eslint-disable-line react-hooks/exhaustive-deps

  // URL → state (intents). Idempotent: re-running on our own URL writes is a no-op.
  React.useEffect(() => {
    const st = useSessionsUI.getState()
    const sid = params.get('session')
    const path = params.get('path')
    if (sid && parseAgentPath(path)) return // redirected above
    for (const id of (params.get('open') || '').split(',').filter(Boolean)) st.openSession(id, { focus: false })
    if (sid) {
      const was = st.focused
      const key = st.openSession(sid)
      // asked from elsewhere (the search, a link): a computer brings its column into view, as a click in the list does
      if (!mobile && key !== was)
        requestAnimationFrame(() => {
          document.querySelector(`[data-col="${key}"]`)?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
          focusComposer(key)
        })
    }
    // A badge was clicked: the tree shows those sessions (and comes back if it was folded away).
    const show = params.get('show')
    if (show === 'running' || show === 'unread') {
      st.setShow(show)
      if (!mobile) useUI.getState().setSecondBarOpen(true)
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
    if (mobile || agentRun) return // leaving for the Agents page (above)
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

  // Tabs view: a chip (or Alt+←/→, a swipe) shows its session - the URL on a phone, the focus on a computer.
  const pickTab = React.useCallback(
    (c: Col) => {
      if (mobile) {
        const path = c.kind === 'new' ? c.path : sessions?.find((s) => s.id === c.id)?.path
        const q = path !== undefined ? `path=${encodeURIComponent(path)}&` : ''
        const url = c.kind === 'new' ? `/sessions?${q}new=1` : `/sessions?${q}session=${c.id}`
        navigate(url, { replace: true })
        return
      }
      useSessionsUI.getState().focus(c.key)
      requestAnimationFrame(() => focusComposer(c.key))
    },
    [mobile, navigate, sessions],
  )

  // Phone: the URL names the session on screen and the state -> URL effect is off. When its column goes (tab closed,
  // session deleted), show the column now focused, else the most recent other session - never a blank screen.
  const prevCols = React.useRef(cols)
  React.useEffect(() => {
    const before = prevCols.current
    prevCols.current = cols
    const id = params.get('session')
    const has = (list: Col[]) => list.some((c) => c.kind === 'session' && c.id === id)
    if (!mobile || !id || has(cols) || !has(before)) return
    const f = cols.find((c) => c.key === focused)
    if (f) return pickTab(f)
    const other = sessions?.filter((s) => s.id !== id).sort((a, b) => b.updated - a.updated)[0]
    navigate(other ? `/sessions?path=${encodeURIComponent(other.path)}&session=${other.id}` : '/sessions', { replace: true })
  }, [cols]) // eslint-disable-line react-hooks/exhaustive-deps

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
      } else if (e.code === 'KeyT') {
        e.preventDefault()
        st.setTabs(!st.tabs)
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

  // ⌘K palette: new session here, the shortcuts (a computer). The recent sessions are the palette's own, on every page.
  useRegisterCommands(
    'sessions',
    [
      ...(defaultTopic !== null
        ? [
            {
              id: 'sessions:new-here',
              title: `${t('palette.newSessionIn')} ${topicLabel(defaultTopic, t('sessions.root'))}`,
              group: t('palette.actions'),
              icon: MessageSquarePlus,
              sensitive: true,
              shortcut: ['Alt', 'N'],
              perform: () => newInCurrent(),
            },
          ]
        : []),
      ...(mobile ? [] : [{ id: 'sessions:shortcuts', title: t('sessions.shortcuts.title'), group: t('palette.actions'), icon: Keyboard, perform: () => setHelpOpen(true) }]),
    ],
    [t, defaultTopic, mobile],
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
  // Mouse: the wheel over the strip but on no session (gap, empty cell, edge) or over a session's header scrolls it
  // sideways, and so does Shift + wheel anywhere on the strip (columns side by side leave no gap to aim at).
  // Trackpad: a sideways swipe anywhere over the columns scrolls the strip. The threads inside contain their
  // overscroll (vertical lists), which swallowed horizontal wheel deltas unless the pointer sat below them.
  // No snapping on a computer: the strip stays where it is scrolled to, it never locks onto a column.
  // Listening on the document (not the strip) keeps working whenever the strip is mounted or re-mounted.
  React.useEffect(() => {
    if (mobile) return
    const onWheel = (e: WheelEvent) => {
      const el = strip.current
      if (!el || !(e.target instanceof Node) || !el.contains(e.target)) return
      if (e.ctrlKey || el.scrollWidth <= el.clientWidth) return
      // Mouse wheel (a pointer that hovers) on no session, on a session's header, or with Shift: the strip scrolls sideways.
      const onHead = e.target instanceof Element && (!e.target.closest('[data-col]') || !!e.target.closest('[data-col-head]'))
      const wheelSideways = (onHead || e.shiftKey) && Math.abs(e.deltaY) > Math.abs(e.deltaX) && window.matchMedia('(hover: hover) and (pointer: fine)').matches
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
      el.scrollLeft += e.deltaMode === 1 ? delta * 16 : delta
    }
    document.addEventListener('wheel', onWheel, { passive: false })
    return () => document.removeEventListener('wheel', onWheel)
  }, [mobile])
  const colEl = (k: string) => strip.current?.querySelector<HTMLElement>(`:scope > [data-col="${CSS.escape(k)}"]`) ?? null
  const colElCb = React.useCallback((k: string) => strip.current?.querySelector<HTMLElement>(`:scope > [data-col="${CSS.escape(k)}"]`) ?? null, [])
  // A place equal to the previous one is the same object: the columns are memoized (ColumnFor), and a focus change
  // or a new row split would otherwise re-render all of them.
  const lastPlaces = React.useRef(new Map<string, Place>())
  const places = React.useMemo(() => {
    const r = computePlaces()
    const prev = lastPlaces.current
    for (const [k, pl] of r.places) {
      const old = prev.get(k)
      if (old && samePlace(old, pl)) r.places.set(k, old)
    }
    lastPlaces.current = r.places
    return r
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownCols, tabs, tabs && focused, rowSplit])
  function computePlaces() {
    const out = new Map<string, Place>()
    if (tabs) {
      // tabs view: every session in the one cell, only the focused one shown (the others stay mounted: no reload)
      const shown = shownCols.some((p) => p.key === focused && !p.leaving) ? focused : shownCols.find((p) => !p.leaving)?.key
      for (const p of shownCols) out.set(p.key, { col: 1, row: 'full', i: 0, n: 1, gridRow: '1 / -1', hidden: p.key !== shown })
      return { places: out, tops: shownCols.length ? [shownCols[0].key] : [], stacks: [] as string[][], rows: stripRows([1], rowSplit) }
    }
    // stacks: a `below` session joins the strip column before it, up to MAX_STACK
    const stacks: string[][] = []
    for (const p of shownCols) {
      const last = stacks[stacks.length - 1]
      if (p.item.below && last && last.length < MAX_STACK) last.push(p.key)
      else stacks.push([p.key])
    }
    const rows = stripRows(stacks.map((g) => g.length), rowSplit)
    stacks.forEach((g, c) => {
      // a half column at an edge of the strip stays there while the others scroll past it
      g.forEach((k, i) =>
        out.set(k, { col: c + 1, row: g.length === 1 ? 'full' : i ? 'bottom' : 'top', i, n: g.length, gridRow: rows.lines(g.length, i), ...(i > 0 && { top: g[0] }) }),
      )
    })
    return { places: out, tops: stacks.map((g) => g[0]), stacks, rows }
  }
  const wide = React.useMemo(() => new Set(cols.filter((c) => c.wide).map((c) => c.key)), [cols])
  const half = React.useMemo(() => new Set(cols.filter((c) => c.half).map((c) => c.key)), [cols])
  // (a row drag reads the stacks of the moment: a session can open or close meanwhile)
  const placesNow = React.useRef(places)
  placesNow.current = places
  // beside a half column, the others fill the other half exactly (as many as fit at MIN_W): none shows cut in two,
  // and scrolling steps one column at a time
  const hasHalf = places.tops.length > 1 && places.tops.some((k) => half.has(k))
  const [beside, setBeside] = React.useState(1)
  React.useLayoutEffect(() => {
    const el = strip.current
    if (!hasHalf || !el) return
    const fit = () => setBeside(Math.max(1, Math.floor(el.clientWidth / 2 / MIN_W)))
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [hasHalf])
  const template = React.useCallback(
    (override?: { key: string; w: number }) =>
      places.tops
        .map((k) => {
          // with a half column no width set by hand counts: the half stays half and the others share the other half
          // exactly (a hand width collapsed the half to MIN_W, or left a column partly under it)
          const w = hasHalf ? undefined : override?.key === k ? override.w : places.tops.length > 1 ? widths[k] : undefined
          // a resized column keeps its width while there is room, then shrinks to MIN_W before the strip scrolls
          if (w) return `minmax(${MIN_W}px, ${Math.round(w)}px)`
          // half the visible strip, whatever the number of columns beside it (they scroll past it)
          if (places.tops.length > 1 && half.has(k)) return `max(${MIN_W}px, 50%)`
          const min = hasHalf ? `max(${MIN_W}px, ${+(50 / beside).toFixed(3)}%)` : `${MIN_W}px`
          return `minmax(${min}, ${places.tops.length > 1 && wide.has(k) ? 2 : 1}fr)`
        })
        .join(' '),
    [places, widths, wide, half, hasHalf, beside],
  )
  const halfNow = React.useRef(hasHalf)
  halfNow.current = hasHalf
  const templateNow = React.useRef(template)
  templateNow.current = template
  const stacked = cols.some((c) => c.below)

  // tabs view: the session that comes on screen slides in from the side of its tab
  const tabShown = tabs ? [...places.places].find(([, pl]) => !pl.hidden)?.[0] : undefined
  useTabSwitchMotion(tabs, tabShown, cols.map((c) => c.key), colElCb)
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
    if (tabs) {
      lastRects.current = new Map()
      return
    }
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
  }, [tabs, cols.map((c) => c.key + (c.below ? 'v' : '') + (c.wide ? 'w' : '') + (c.half ? 'h' : '') + (widths[c.key] ?? '')).join(' ')]) // eslint-disable-line react-hooks/exhaustive-deps

  // Resizing: the column handle (width of a grid column) and the row handle (height split of stacked sessions) set
  // the grid template live, then save it.
  const strip_ = React.useMemo(
    () => ({
      startColResize: (key: string, e: React.PointerEvent) => {
        const el = colEl(key)
        const st = strip.current
        if (!el || !st || halfNow.current) return
        // (the bottom session's handle resizes the same grid column: its width is saved under the top key)
        e.preventDefault()
        const startX = e.clientX
        const startW = el.getBoundingClientRect().width
        const target = e.currentTarget as HTMLElement
        target.setPointerCapture(e.pointerId)
        let w = startW
        // never wider than the strip can show (the others keep MIN_W): past it the handle would move for nothing
        const room = Math.max(startW, st.clientWidth - 8 - (placesNow.current.tops.length - 1) * MIN_W)
        // one grid change per frame (pointer events can come faster, each relays out every open session)
        let frame = 0
        let moved = false
        const onMove = (ev: PointerEvent) => {
          moved ||= Math.abs(ev.clientX - startX) >= 2
          if (!moved) return
          w = Math.max(MIN_W, Math.min(MAX_W, room, startW + ev.clientX - startX))
          frame ||= requestAnimationFrame(() => {
            frame = 0
            st.style.gridTemplateColumns = templateNow.current({ key, w })
          })
        }
        const onUp = () => {
          cancelAnimationFrame(frame)
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          // a click without a drag keeps the column as it was (a saved width would stop it following the window)
          if (moved) useSessionsUI.getState().setWidth(key, w)
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
        let frame = 0
        const onMove = (ev: PointerEvent) => {
          r = Math.max(ROW_SPLIT_MIN, Math.min(ROW_SPLIT_MAX, (ev.clientY - box.top) / box.height))
          frame ||= requestAnimationFrame(apply)
        }
        // one grid change per frame (pointer events can come faster, each relays out every open session)
        const apply = () => {
          frame = 0
          // pairs and trios share the grid rows: when the split crosses a third, every stack's lines change
          const { stacks } = placesNow.current
          const live = stripRows(stacks.map((g) => g.length), r)
          st.style.gridTemplateRows = live.template
          for (const g of stacks)
            g.forEach((k, i) => {
              const el = colEl(k)
              if (el) el.style.gridRow = live.lines(g.length, i)
            })
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          cancelAnimationFrame(frame)
          apply()
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
    // stable while the number of columns stays: every column reads this context (a new value re-renders them all)
    [places.tops.length], // eslint-disable-line react-hooks/exhaustive-deps
  )

  const openIds = React.useMemo(() => new Set(cols.flatMap((c) => (c.kind === 'session' ? [c.id] : []))), [cols])

  const header = (
    <PageHeader
      title={t('nav.sessions')}
      description={<SubtitleWithBadges text={t('sessions.description')} />}
      actions={
        <>
          {!mobile && <TabsToggle compact />}
          {!mobile && !tabs && cols.length >= 2 && (
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
        {!mobile && (
          <PageList id="sessions" label={t('nav.sessions')} search={{ value: listQuery, onChange: setListQuery, placeholder: t('sessions.tree.search') }}>
            {/* the agents listed under their topic show their Office card on hover */}
            <AgentHover className="min-h-0 flex-1">
              <SessionTree className="min-h-0 flex-1" query={listQuery} onOpenSession={openSession} onNewSession={newSession} activePath={currentTopic ?? null} openIds={openIds} focusedId={focusedId} />
            </AgentHover>
          </PageList>
        )}
        {!mobile && (
          <StripContext.Provider value={strip_}>
          <div className={cn('relative flex min-w-0 flex-1', tabs && 'flex-col')}>
          {tabs && <TabsBar sessions={sessions} onPick={pickTab} />}
          {!tabs && <LayoutDropBar />}
          {tabs && <TabsArrows onPick={pickTab} />}
          <div
            ref={strip}
            className={cn('group/strip relative min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-hidden', !tabs && 'pr-2', shownCols.length ? 'grid' : 'flex')}
            style={shownCols.length ? { gridTemplateColumns: template(), gridTemplateRows: places.rows.template } : undefined}
            data-columns
            // several sessions side by side: messages show their grip (drag one into another session, contentDrag.ts)
            data-multi={(!tabs && shownCols.length > 1) || undefined}
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
                      {!listOpen && (
                        <Button variant="outline" onClick={() => setListOpen(true)}>
                          <PanelLeftOpen /> {t('sessions.tree.show')}
                        </Button>
                      )}
                      <Button variant="ghost" onClick={() => setHelpOpen(true)}>
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
      {mobileOpen && focusedCol && <MobileOverlay col={focusedCol} tabs={tabs} sessions={sessions} onPick={pickTab} />}
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
function MobileOverlay({ col, tabs, sessions, onPick }: { col: Col; tabs: boolean; sessions: Session[] | undefined; onPick: (c: Col) => void }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const body = React.useRef<HTMLDivElement>(null)
  const go = React.useCallback(
    (dir: -1 | 1) => {
      const c = stepCol(dir)
      if (c) onPick(c)
    },
    [onPick],
  )
  useSwipe(body, tabs, go)
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
      <div ref={body} className="flex min-h-0 flex-1 flex-col">
        <MobileTabsSlot.Provider value={tabs ? <TabsBar sessions={sessions} onPick={onPick} className="-mx-3 border-b-0 bg-transparent px-3 py-1" /> : null}>
          <ColumnFor col={col} index={0} count={1} variant="mobile" />
        </MobileTabsSlot.Provider>
      </div>
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
    [['Alt', 'T'], t('tabs.toggle')],
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

/** Page subtitle: the words in [brackets] (project, then topic) become badges that explain them on hover. */
function SubtitleWithBadges({ text }: { text: string }) {
  const t = useT()
  const kinds = ['project', 'topic'] as const
  let n = 0
  return (
    <>
      {text.split(/(\[[^\]]+\])/).map((part, i) => {
        const m = /^\[(.+)\]$/.exec(part)
        if (!m) return part
        const kind = kinds[Math.min(n++, 1)]
        return (
          <WhereBadge key={i} kind={kind} name={m[1]} hint={t('where.howTo')} generic>
            {kind === 'project' ? <FolderOpen className="size-3 shrink-0 opacity-70" /> : <Hash className="size-3 shrink-0 opacity-70" />}
          </WhereBadge>
        )
      })}
    </>
  )
}

const samePlace = (a: Place, b: Place) =>
  a.col === b.col && a.row === b.row && a.i === b.i && a.n === b.n && a.gridRow === b.gridRow && a.top === b.top && a.hidden === b.hidden

