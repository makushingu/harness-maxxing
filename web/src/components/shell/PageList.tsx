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
import { Link } from 'react-router'
import { create } from 'zustand'
import { ChevronLeft, PanelLeftClose, PanelLeftOpen, Search, X } from 'lucide-react'
import { SECOND_W, useUI } from '@/stores/ui'
import { useCompact } from '@/stores/media'
import { ResizeEdge } from './ResizeEdge'
import { searchNow, useTouchNav } from './TouchNav'
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
        'mx-list border-x border-sidebar-border text-sidebar-foreground',
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

/** The page's list in the second-level sidebar, with its head (the page's name and the open / close button). Touch
 *  layout: in the left drawer, or in the page itself while `inline` (nothing is picked yet: the list is the page). */
/** The list's own filter: the 🔍 of its head shows a field under it that narrows the list (a list without one: the 🔍
 *  of the touch head opens the search of the app instead, Ctrl K on a desktop). */
export type ListSearch = { value: string; onChange: (v: string) => void; placeholder?: string }

export function PageList({ id, entry, label, icon: Icon, inline, search, actions, children }: {
  id: string
  /** the main sidebar entry that shows the list on hover when closed, when it is not the page's own (`id`) */
  entry?: string
  label: string
  icon?: React.ComponentType<{ className?: string }>
  /** touch layout: shown in the page, in place (no drawer to open, no ☰) */
  inline?: boolean
  search?: ListSearch
  /** small buttons of the list itself (its view, its sort), in its head */
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  const t = useT()
  const slot = useLists((s) => s.slot)
  const open = useUI((s) => s.secondBarOpen)
  const setOpen = useUI((s) => s.setSecondBarOpen)
  const touch = useCompact()
  const here = touch && !!inline
  React.useLayoutEffect(() => {
    if (here) return
    useLists.setState({ list: id, entry: entry ?? id })
    const a = armed
    armed = null
    if (a && a.entry === (entry ?? id) && Date.now() - a.at < 5000 && !useUI.getState().secondBarOpen && a.el.isConnected && a.el.matches(':hover')) {
      opening = false
      useLists.setState({ peek: true })
    }
    return () => useLists.setState((s) => (s.list === id ? { list: null, entry: null, peek: false } : s))
  }, [id, entry, here])
  if (here) return <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="page-list-inline">{children}</div>
  if (!slot) return null
  const toggle = open ? t('shell.listHide') : t('shell.listKeep')
  return createPortal(
    <>
      <ListHead label={label} icon={Icon} search={search}>
        {actions}
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
export function ListHead({ label, icon: Icon, search, children }: { label: string; icon?: React.ComponentType<{ className?: string }>; search?: ListSearch; children?: React.ReactNode }) {
  const t = useT()
  const touch = useCompact()
  const [asked, setAsked] = React.useState(false)
  const field = !!search && (asked || !!search.value)
  const close = () => {
    search?.onChange('')
    setAsked(false)
  }
  const glass = search ? (field ? close : () => setAsked(true)) : touch ? searchNow : null
  const glassLabel = search ? search.placeholder || t('common.search') : t('palette.open')
  return (
    <>
    <div className={cn('flex min-h-[var(--header-h)] shrink-0 items-center gap-2 border-b border-sidebar-border pr-2', touch ? 'pl-1.5' : 'pl-4')}>
      {/* touch: the list is the drawer's second level - ‹ goes back to the menu */}
      {touch && (
        <button
          type="button"
          onClick={() => useTouchNav.getState().setPanel('app')}
          aria-label={t('shell.menu')}
          data-testid="touch-back"
          className="-mr-1 flex size-10 shrink-0 items-center justify-center rounded-lg text-muted-foreground outline-none active:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronLeft className="size-[22px]" />
        </button>
      )}
      {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      <h2 className="min-w-0 flex-1 truncate text-base font-semibold tracking-tight">{label}</h2>
      {/* the search, facing the title: the list's filter, or (touch, a list without one) the search of the app */}
      {glass && (touch ? (
        <button
          type="button"
          onClick={glass}
          aria-label={glassLabel}
          aria-pressed={search ? field : undefined}
          data-testid="touch-search-field"
          className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg text-muted-foreground outline-none active:bg-accent focus-visible:ring-2 focus-visible:ring-ring', field && 'text-foreground')}
        >
          <Search className="size-5" />
        </button>
      ) : (
        <Tooltip content={glassLabel}>
          <Button variant="ghost" size="icon-sm" aria-label={glassLabel} aria-pressed={field} className={cn('shrink-0 text-muted-foreground', field && 'bg-accent text-foreground')} onClick={glass} data-testid="list-search">
            <Search />
          </Button>
        </Tooltip>
      ))}
      {children}
    </div>
    {field && search && (
      <div className={cn('relative shrink-0', touch ? 'px-3 pt-2' : 'px-2 pt-2')}>
        <Search className={cn('pointer-events-none absolute top-1/2 mt-1 size-4 -translate-y-1/2 text-muted-foreground', touch ? 'left-6' : 'left-4.5')} />
        <input
          autoFocus={asked}
          value={search.value}
          onChange={(e) => search.onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              close()
            }
          }}
          placeholder={search.placeholder || t('common.search')}
          aria-label={search.placeholder || t('common.search')}
          className={cn('w-full rounded-lg border border-input bg-transparent pr-8 pl-8 text-sm outline-none placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 dark:bg-input/30', touch ? 'h-10 text-base' : 'h-8')}
          data-testid="list-search-field"
        />
        {search.value && (
          <button type="button" onClick={() => search.onChange('')} aria-label={t('common.close')} className={cn('absolute top-1/2 mt-1 flex size-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:text-foreground', touch ? 'right-4.5' : 'right-3.5')}>
            <X className="size-3.5" />
          </button>
        )}
      </div>
    )}
    </>
  )
}

/** A row of filters at the top of a list (All / Running / Unread…): one line, the one picked filled. `count` shows after
 *  the label, `dot` before it. Touch: equal parts in a grey track. */
export function ListChips<K extends string>({ items, value, onChange, label, className }: {
  items: { key: K; label: string; count?: number; dot?: React.ReactNode; testid?: string }[]
  value: K
  onChange: (k: K) => void
  label: string
  className?: string
}) {
  const touch = useCompact()
  return (
    <div
      className={cn('shrink-0', touch ? 'flex gap-1 overflow-x-auto rounded-xl bg-muted p-1' : '-my-1 flex gap-1.5 overflow-x-auto py-1', className)}
      role="group"
      aria-label={label}
      data-hscroll-ok
    >
      {items.map((it) => {
        const on = it.key === value
        return (
          <button
            key={it.key}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(it.key)}
            data-testid={it.testid}
            className={cn(
              'flex items-center font-medium whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
              touch ? 'h-9 shrink-0 flex-auto justify-center gap-1 rounded-lg px-2.5 text-[13px]' : 'h-6 shrink-0 gap-1.5 rounded-full px-2 text-xs',
              on ? 'bg-foreground text-background' : cn('text-muted-foreground hover:text-foreground', touch ? 'active:bg-accent' : 'bg-muted active:bg-accent'),
            )}
          >
            {it.dot}
            <span className="truncate">{it.label}</span>
            {!!it.count && <span className="tabular-nums opacity-70">{it.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** An entry of a list's navigation (Overview, All tasks, All mailboxes…): the same row on every page. A link (`to`) or a
 *  button (`onClick`); `count` at the end (a plain total), `badge` before it (to read, problems). */
export function ListEntry({ icon: Icon, label, to, onClick, active, count, badge, testid, className }: {
  icon: React.ComponentType<{ className?: string }>
  label: React.ReactNode
  to?: string
  onClick?: () => void
  active?: boolean
  count?: number
  badge?: React.ReactNode
  testid?: string
  className?: string
}) {
  const touch = useCompact()
  const cls = cn(
    'flex w-full min-w-0 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
    touch ? 'h-11' : 'h-9',
    active && 'bg-accent font-medium text-foreground hover:bg-accent',
    className,
  )
  const body = (
    <>
      <Icon className={cn('size-4 shrink-0', active && 'text-primary')} />
      <span className="min-w-0 flex-1 truncate text-left">{label}</span>
      {badge}
      {count != null && count > 0 && <span className="min-w-5 text-right text-xs tabular-nums text-muted-foreground">{count}</span>}
    </>
  )
  return to ? (
    <Link to={to} aria-current={active ? 'page' : undefined} className={cls} data-testid={testid}>
      {body}
    </Link>
  ) : (
    <button type="button" onClick={onClick} aria-current={active ? 'page' : undefined} className={cls} data-testid={testid}>
      {body}
    </button>
  )
}
