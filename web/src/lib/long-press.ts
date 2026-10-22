// Long press on touch screens (iPhone Safari never fires `contextmenu`): opens a row's menu. The finger must stay
// still; the touchend that follows is cancelled so the row's own tap action does not run as well.
import * as React from 'react'

const HOLD_MS = 450
const SLOP = 8

export type LongPressHandlers = Pick<React.HTMLAttributes<HTMLElement>, 'onTouchStart' | 'onTouchMove' | 'onTouchEnd' | 'onTouchCancel'>

export function useLongPress(onFire: () => void): LongPressHandlers {
  const fire = React.useRef(onFire)
  fire.current = onFire
  const press = React.useRef<{ timer: number; x: number; y: number } | null>(null)
  const fired = React.useRef(false)
  const cancel = () => {
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
  }
  React.useEffect(() => cancel, [])
  return React.useMemo<LongPressHandlers>(
    () => ({
      onTouchStart: (e) => {
        cancel()
        fired.current = false
        const p = e.touches[0]
        if (e.touches.length !== 1 || !p) return
        press.current = {
          x: p.clientX,
          y: p.clientY,
          timer: window.setTimeout(() => {
            press.current = null
            fired.current = true
            if (navigator.vibrate) navigator.vibrate(8)
            fire.current()
          }, HOLD_MS),
        }
      },
      onTouchMove: (e) => {
        const p = e.touches[0]
        if (press.current && p && Math.hypot(p.clientX - press.current.x, p.clientY - press.current.y) > SLOP) cancel()
      },
      onTouchEnd: (e) => {
        cancel()
        if (fired.current) e.preventDefault()
      },
      onTouchCancel: cancel,
    }),
    [],
  )
}
