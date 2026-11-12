// Right click on an item (a long press on touch screens) opens its menu at the pointer - the same items as its "..."
// menu: keep them in one variable (or component) and render it in both places.
//
//   const ctx = useContextMenu()
//   const items = <>…DropdownMenuItem…</>
//   <li {...ctx.props}>
//     …<DropdownMenu><DropdownMenuTrigger>…</DropdownMenuTrigger><DropdownMenuContent>{items}</DropdownMenuContent></DropdownMenu>
//     {ctx.menu(items)}
//   </li>
//
// The browser's own menu stays where it is worth more: on fields, on text the user has selected, on links (unless
// `links: true`: then the items should offer "Open in new tab"). A nested item with its own menu wins over its parent.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useLongPress } from '@/lib/long-press'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from './dropdown-menu'

export type ContextMenuHandlers = Pick<React.HTMLAttributes<HTMLElement>, 'onContextMenu' | 'onTouchStart' | 'onTouchMove' | 'onTouchEnd' | 'onTouchCancel'>

const FIELD = 'input, textarea, select, [contenteditable=""], [contenteditable="true"], [data-native-menu]'

/** True when a right click on `target` should keep the browser's menu: a field, selected text, a link (`links`). */
export function wantsNativeMenu(target: EventTarget | null, links = true): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest(FIELD)) return true
  if (links && target.closest('a[href]')) return true
  const sel = window.getSelection()
  return !!sel && !sel.isCollapsed && !!sel.toString().trim() && sel.containsNode(target, true)
}

const stop = (e: React.SyntheticEvent) => e.stopPropagation()

type Options = {
  /** No menu (an item without actions, a mode where its actions do not apply). */
  disabled?: boolean
  /** Also take over the right click on links inside the item (default: the browser's menu, "Open in new tab"…). */
  links?: boolean
  /** Also open on a long press on touch screens (default); off where the long press already means something (drag). */
  touch?: boolean
}

// Each opening gets a new key (a module counter: a close and a reopen batched together still remount it).
let opened = 0

export function useContextMenu({ disabled = false, links = false, touch = true }: Options = {}) {
  // `n` remounts the menu on each opening, so a second right click moves it to the new point.
  const [at, setAt] = React.useState<{ x: number; y: number; n: number } | null>(null)
  const last = React.useRef({ x: 0, y: 0 })
  const pressed = React.useRef(0)
  const content = React.useRef<HTMLDivElement | null>(null)
  const openAt = React.useCallback((x: number, y: number) => setAt({ x, y, n: ++opened }), [])
  const press = useLongPress(() => {
    pressed.current = Date.now()
    openAt(last.current.x, last.current.y)
  })

  // Fixed at the point it was opened: it closes when the page scrolls under it (not when its own list scrolls).
  const open = !!at
  React.useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e.target instanceof Node && content.current?.contains(e.target)) return
      setAt(null)
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  const props: ContextMenuHandlers = disabled
    ? {}
    : {
        onContextMenu: (e) => {
          if (e.defaultPrevented || wantsNativeMenu(e.target, !links)) return
          e.preventDefault()
          if (!touch && (e.nativeEvent as PointerEvent).pointerType === 'touch') return
          // Android: the long press already opened it; its own contextmenu event follows.
          if (Date.now() - pressed.current < 1500) return
          openAt(e.clientX, e.clientY)
        },
        ...(touch && press),
        onTouchStart: touch ? (e) => {
          // A nested item with its own menu takes the long press; fields keep theirs (selecting text).
          const ev = e.nativeEvent as TouchEvent & { mxContextMenu?: boolean }
          if (ev.mxContextMenu || wantsNativeMenu(e.target, !links)) return
          ev.mxContextMenu = true
          const p = e.touches[0]
          if (p) last.current = { x: p.clientX, y: p.clientY }
          press.onTouchStart?.(e)
        } : undefined,
      }

  /** The menu at the pointer, with `items` (the same nodes as the "..." menu). Renders nothing while closed. */
  const menu = (items: React.ReactNode, contentProps?: Omit<React.ComponentProps<typeof DropdownMenuContent>, 'children'>) =>
    at &&
    typeof document !== 'undefined' && (
      <DropdownMenu key={at.n} open modal={false} onOpenChange={(o) => !o && setAt(null)}>
        {createPortal(
          <DropdownMenuTrigger asChild>
            <span aria-hidden tabIndex={-1} className="pointer-events-none fixed size-0" style={{ left: at.x, top: at.y }} />
          </DropdownMenuTrigger>,
          document.body,
        )}
        {/* Portaled, but React events still bubble to the item: its click / drag / long press must not see them. */}
        <DropdownMenuContent
          ref={content}
          align="start"
          sideOffset={2}
          collisionPadding={8}
          data-testid="context-menu"
          {...contentProps}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onClick={stop}
          onDoubleClick={stop}
          onKeyDown={stop}
          onPointerDown={stop}
          onMouseDown={stop}
          onTouchStart={stop}
          onTouchMove={stop}
          onTouchEnd={stop}
          onTouchCancel={stop}
          onContextMenu={(e) => {
            e.preventDefault()
            e.stopPropagation()
          }}
        >
          {items}
        </DropdownMenuContent>
      </DropdownMenu>
    )

  return { props, menu, open, openAt, close: () => setAt(null) }
}

/** The same, for an item rendered inline (a `.map` row): `<WithContextMenu items={…}><li …/></WithContextMenu>`.
 *  Its handlers are added to the child's own; no `items` (null, false) = no menu. */
export function WithContextMenu({
  items,
  links,
  className,
  children,
}: {
  items: React.ReactNode
  links?: boolean
  /** The menu's class (its width). */
  className?: string
  children: React.ReactElement<ContextMenuHandlers>
}) {
  const ctx = useContextMenu({ disabled: items == null || items === false, links })
  const own = children.props
  const merged: ContextMenuHandlers = {}
  for (const k of Object.keys(ctx.props) as (keyof ContextMenuHandlers)[]) {
    const a = own[k] as ((e: React.SyntheticEvent) => void) | undefined
    const b = ctx.props[k] as ((e: React.SyntheticEvent) => void) | undefined
    if (!b) continue
    merged[k] = (a ? (e: React.SyntheticEvent) => (a(e), b(e)) : b) as never
  }
  return (
    <>
      {React.cloneElement(children, merged)}
      {ctx.menu(items, { className })}
    </>
  )
}
