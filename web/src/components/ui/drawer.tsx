// Side drawer of the touch layout (sessions on the left, the app on the right). Unlike Sheet it stays a side panel on
// phones. Swipe it back towards its edge to close it; the overlay fades with the finger.
import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { cn, mergeRefs } from '@/lib/utils'

export const Drawer = DialogPrimitive.Root

type Side = 'left' | 'right'

const NO_DRAG = 'input, textarea, select, [contenteditable=""], [contenteditable="true"], [data-no-drag], [role="slider"]'

function useSwipeClose(side: Side, onDismiss: () => void, overlay: React.RefObject<HTMLElement | null>) {
  const dismiss = React.useRef(onDismiss)
  dismiss.current = onDismiss
  return React.useCallback(
    (node: HTMLElement | null) => {
      if (!node) return
      const sign = side === 'left' ? -1 : 1 // direction that closes
      let x0 = 0
      let y0 = 0
      let dx = 0
      let t0 = 0
      let state: 'idle' | 'maybe' | 'drag' | 'off' = 'idle'
      const set = (x: number, animate: boolean) => {
        node.style.transition = animate ? 'transform 240ms cubic-bezier(0.32, 0.72, 0, 1)' : 'none'
        node.style.transform = x ? `translateX(${x}px)` : ''
        const o = overlay.current
        if (o) {
          o.style.transition = animate ? 'opacity 240ms ease' : 'none'
          o.style.opacity = x ? String(Math.max(0, 1 - Math.abs(x) / node.offsetWidth)) : ''
        }
      }
      const start = (e: TouchEvent) => {
        state = 'idle'
        if (e.touches.length !== 1 || (e.target as Element).closest(NO_DRAG)) return
        x0 = e.touches[0].clientX
        y0 = e.touches[0].clientY
        t0 = performance.now()
        dx = 0
        state = 'maybe'
      }
      const move = (e: TouchEvent) => {
        if (state === 'idle' || state === 'off') return
        const x = e.touches[0].clientX - x0
        const y = e.touches[0].clientY - y0
        if (state === 'maybe') {
          if (Math.abs(x) < 6 && Math.abs(y) < 6) return
          // Towards the edge and mostly horizontal: the drawer takes the gesture (a vertical one scrolls the list).
          if (Math.sign(x) !== sign || Math.abs(y) > Math.abs(x)) {
            state = 'off'
            return
          }
          state = 'drag'
          x0 += x
          t0 = performance.now()
        }
        e.preventDefault()
        const d = e.touches[0].clientX - x0
        dx = Math.sign(d) === sign ? d : 0
        set(dx, false)
      }
      const end = () => {
        if (state !== 'drag') {
          state = 'idle'
          return
        }
        state = 'idle'
        const speed = Math.abs(dx) / Math.max(16, performance.now() - t0)
        if (Math.abs(dx) > node.offsetWidth * 0.3 || (Math.abs(dx) > 24 && speed > 0.5)) {
          node.style.transition = 'none'
          if (overlay.current) overlay.current.style.transition = 'none'
          dismiss.current()
        } else set(0, true)
      }
      node.addEventListener('touchstart', start, { passive: true })
      node.addEventListener('touchmove', move, { passive: false })
      node.addEventListener('touchend', end)
      node.addEventListener('touchcancel', end)
      return () => {
        node.removeEventListener('touchstart', start)
        node.removeEventListener('touchmove', move)
        node.removeEventListener('touchend', end)
        node.removeEventListener('touchcancel', end)
      }
    },
    [side, overlay],
  )
}

export function DrawerContent({ side, className, children, ref, ...props }: React.ComponentProps<typeof DialogPrimitive.Content> & { side: Side }) {
  const overlay = React.useRef<HTMLDivElement>(null)
  const close = React.useRef<HTMLButtonElement>(null)
  const swipe = useSwipeClose(side, () => close.current?.click(), overlay)
  const refs = React.useMemo(() => mergeRefs(ref, swipe), [ref, swipe])
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay ref={overlay} className="fixed inset-0 z-50 bg-overlay data-[state=closed]:animate-overlay-out data-[state=open]:animate-overlay-in" />
      <DialogPrimitive.Content
        ref={refs}
        className={cn(
          'fixed inset-y-0 z-50 flex w-[min(88vw,380px)] flex-col bg-sidebar text-foreground outline-none will-change-transform',
          'pt-[var(--safe-top)] pb-[var(--safe-bottom-ui)]',
          side === 'left'
            ? 'left-0 border-r border-sidebar-border pl-[var(--safe-left)] data-[state=closed]:animate-sheet-left-out data-[state=open]:animate-sheet-left'
            : 'right-0 border-l border-sidebar-border pr-[var(--safe-right)] data-[state=closed]:animate-sheet-right-out data-[state=open]:animate-sheet-right',
          className,
        )}
        {...props}
      >
        <DialogPrimitive.Close ref={close} hidden tabIndex={-1} aria-hidden />
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

export const DrawerTitle = DialogPrimitive.Title
export const DrawerClose = DialogPrimitive.Close
