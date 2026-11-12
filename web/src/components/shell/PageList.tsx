// The second-level sidebar (desktop): the list of the page open (Sessions, Agents, Team), full height beside the main
// sidebar. The page renders its list with <PageList> (a portal into the slot the sidebar keeps right of itself,
// SecondBar), so the list keeps the page's own state and handlers. One setting for every page (`ui.secondBarOpen`):
// open, it takes its room and the page follows; closed, nothing is left of it, and resting on the page's own entry in
// the main sidebar shows it over the page until the pointer leaves (a click elsewhere, Esc or a pick in it too); a click
// on that entry opens it for good (and a click that opens the page shows it at once). Its head has the button that
// opens / closes it. A page without a list has no second sidebar.
// Touch layout: no sidebar; the same list opens in the left drawer (TouchNav.tsx: the ☰ of the page's header, shown only
// when the page has a list), whose body is the slot (ListSlot).
import * as React from 'react'
import { createPortal } from 'react-dom'
import { create } from 'zustand'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { SECOND_W, useUI } from '@/stores/ui'
import { useCompact } from '@/stores/media'
import { ResizeEdge } from './ResizeEdge'
import { TouchSearchField } from './TouchNav'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { Button, Tooltip } from '@/components/ui'

/** Hover intent before a closed list shows; grace to cross from the sidebar entry to the list (or back) before it goes. */
const OPEN_MS = 140
const CLOSE_MS = 220

/** `slot`: where the lists go (SecondBar, or the touch drawer's ListSlot); `list`: the id of the page's list mounted;
 *  `entry`: the main sidebar entry that shows it on hover when closed (its path without the slash); `peek`: shown over
 *  the page. */
const useLists = create<{ slot: HTMLElement | null; list: string | null; entry: string | null; peek: boolean }>(() => ({ slot: null, list: null, entry: null, peek: false }))
let timer: number | undefined
/** A peek is on its way (the hover intent delay runs). */
let opening = false

/** A menu or dialog opened from the list (a row's ⋯, a context menu) keeps it until it closes. */
const busy = () => !!document.querySelector('[role="menu"][data-state="open"], [role="dialog"][data-state="open"]')

const peekList = () => {
  window.clearTimeout(timer)
  opening = !useLists.getState().peek
  if (opening)
    timer = window.setTimeout(() => {
      opening = false
      useLists.setState({ peek: true })
    }, OPEN_MS)
}
const leaveList = () => {
  window.clearTimeout(timer)
  opening = false
  const close = () => {
    if (busy()) timer = window.setTimeout(close, CLOSE_MS)
    else useLists.setState({ peek: false })
  }
  if (useLists.getState().peek) timer = window.setTimeout(close, CLOSE_MS)
}
const closeList = () => {
  window.clearTimeout(timer)
  opening = false
  useLists.setState({ peek: false })
}

/** The id of the page open's list when the second-level sidebar is closed (its main sidebar entry then shows it on
 *  hover), else null. */
export function useClosedList() {
  const entry = useLists((s) => s.entry)
  const open = useUI((s) => s.secondBarOpen)
  return open ? null : entry
}

/** A click on a main sidebar entry that opens another page: if that page has a list and the second-level sidebar is
 *  closed, the list shows over the page while the pointer stays on the entry (it was already on it, so no new hover
 *  would show it). */
let armed: { entry: string; el: Element; at: number } | null = null
export const armEntryPeek = (entry: string, e: React.MouseEvent) => {
  armed = e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey ? { entry, el: e.currentTarget, at: Date.now() } : null
}

/** The id of the list of the page open (null: the page has none). */
export const usePageListId = () => useLists((s) => s.list)
export const pageListId = () => useLists.getState().list

/** Touch layout: the body of the left drawer, where the page's list goes while it is open. */
export function ListSlot({ className }: { className?: string }) {
  const set = React.useCallback((el: HTMLDivElement | null) => useLists.setState({ slot: el }), [])
  return <div ref={set} className={className} data-testid="list-slot" />
}
/** Handlers of that entry. Hover shows the list over the page; `pointermove` too, so the list of a page just opened
 *  from this entry shows without leaving and entering it again (the pointer was already on it). A plain click (the
 *  page is already open) docks the list: the second-level sidebar opens and stays. */
export const entryPeek = {
  onPointerEnter: (e: React.PointerEvent) => e.pointerType === 'mouse' && peekList(),
  onPointerMove: (e: React.PointerEvent) => e.pointerType === 'mouse' && !opening && !useLists.getState().peek && peekList(),
  onPointerLeave: (e: React.PointerEvent) => e.pointerType === 'mouse' && leaveList(),
  onClick: (e: React.MouseEvent) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    closeList()
    useUI.getState().setSecondBarOpen(true)
  },
}

/** The slot of the second-level sidebar, right of the main sidebar (Sidebar.tsx): in the flow when open, over the page
 *  when shown from a hover. `left`: the main sidebar's width. */
export function SecondBar({ left }: { left: number }) {
  const list = useLists((s) => s.list)
  const peek = useLists((s) => s.peek)
  const open = useUI((s) => s.secondBarOpen)
  const width = useUI((s) => s.secondBarWidth) ?? SECOND_W.default
  const setWidth = useUI((s) => s.setSecondBarWidth)
  const ref = React.useRef<HTMLDivElement>(null)
  const box = React.useRef<HTMLDivElement>(null)
  React.useLayoutEffect(() => {
    useLists.setState({ slot: box.current })
    return () => useLists.setState({ slot: null })
  }, [])
  const over = !!list && !open
  const shown = !!list && (open || peek)

  // Shown over the page: a click elsewhere (outside its menus and cards) or Esc puts it away.
  React.useEffect(() => {
    if (!over || !peek) return
    const onDown = (e: PointerEvent) => {
      const el = e.target as Element
      if (!ref.current?.contains(el) && !el.closest?.('[data-radix-popper-content-wrapper], [role="menu"], [role="dialog"], [data-list-entry]')) closeList()
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy() && closeList()
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [over, peek])
  React.useEffect(() => {
    if (!over) closeList()
  }, [over])
  // Native listeners: the list is a portal from the page, so React's own enter / leave / click events of this element
  // follow the page's tree, not this one.
  React.useEffect(() => {
    const el = ref.current
    if (!el || !over) return
    const enter = (e: PointerEvent) => e.pointerType === 'mouse' && peekList()
    const leave = (e: PointerEvent) => e.pointerType === 'mouse' && leaveList()
    // a pick in the list shown over the page (a session, an agent, a chat) puts it away
    const click = (e: MouseEvent) => (e.target as Element).closest('a[href], [data-session-row], [data-chat-row]') && window.setTimeout(closeList)
    el.addEventListener('pointerenter', enter)
    el.addEventListener('pointerleave', leave)
    el.addEventListener('click', click, true)
    return () => {
      el.removeEventListener('pointerenter', enter)
      el.removeEventListener('pointerleave', leave)
      el.removeEventListener('click', click, true)
    }
  }, [over])

  return (
    <div
      ref={ref}
      className={cn(
        'border-r border-sidebar-border bg-sidebar text-sidebar-foreground',
        !list ? 'hidden' : over ? 'mx-list-peek absolute inset-y-0' : 'relative shrink-0',
      )}
      style={{ width, left: over ? left : undefined }}
      data-testid="second-bar"
      data-list={list || undefined}
      data-open={open || undefined}
      data-on={shown || undefined}
      inert={over && !peek ? true : undefined}
    >
      {/* the page's list comes in here (PageList) */}
      <div ref={box} className="flex h-full min-h-0 flex-col" />
      {list && <ResizeEdge side={ref} min={SECOND_W.min} max={SECOND_W.max} onWidth={setWidth} />}
    </div>
  )
}

/** The page's list in the second-level sidebar, with its head (the page's name and the open / close button). Desktop
 *  only: the touch layout has its own drawers. */
export function PageList({ id, entry, label, icon: Icon, children }: {
  id: string
  /** the main sidebar entry that shows the list on hover when closed, when it is not the page's own (`id`) */
  entry?: string
  label: string
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  const t = useT()
  const slot = useLists((s) => s.slot)
  const open = useUI((s) => s.secondBarOpen)
  const setOpen = useUI((s) => s.setSecondBarOpen)
  const touch = useCompact()
  React.useLayoutEffect(() => {
    useLists.setState({ list: id, entry: entry ?? id })
    const a = armed
    armed = null
    if (a && a.entry === (entry ?? id) && Date.now() - a.at < 5000 && !useUI.getState().secondBarOpen && a.el.isConnected && a.el.matches(':hover')) {
      opening = false
      useLists.setState({ peek: true })
    }
    return () => useLists.setState((s) => (s.list === id ? { list: null, entry: null, peek: false } : s))
  }, [id, entry])
  if (!slot) return null
  const toggle = open ? t('shell.listHide') : t('shell.listKeep')
  return createPortal(
    <>
      <ListHead label={label} icon={Icon}>
        {!touch && <Tooltip content={toggle}>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={toggle}
            aria-pressed={open}
            className="shrink-0 text-muted-foreground"
            data-testid="list-toggle"
            onClick={() => {
              closeList()
              setOpen(!open)
            }}
          >
            {open ? <PanelLeftClose /> : <PanelLeftOpen />}
          </Button>
        </Tooltip>}
      </ListHead>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </>,
    slot,
  )
}

/** The head of a list (its page's name): the second-level sidebar's, and the touch drawers' (the sessions drawer has
 *  its own body but the same head). */
export function ListHead({ label, icon: Icon, children }: { label: string; icon?: React.ComponentType<{ className?: string }>; children?: React.ReactNode }) {
  const touch = useCompact()
  return (
    <>
    <div className="flex min-h-[var(--header-h)] shrink-0 items-center gap-2 border-b border-sidebar-border pr-2 pl-4">
      {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      <h2 className="min-w-0 flex-1 truncate text-base font-semibold tracking-tight">{label}</h2>
      {children}
    </div>
    {/* touch: the drawers' search field (a computer has the sidebar's) */}
    {touch && <TouchSearchField />}
    </>
  )
}
