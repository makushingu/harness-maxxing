// Touch screens: no page zoom, and keep the layout steady around the on-screen keyboard (iOS home-screen apps above all).
// - html[data-kbd] while a field has the focus: the tab bar steps aside and the bottom insets drop to 0
//   (the keyboard covers the home indicator), so nothing floats above the keys.
// - --kbd-inset = how much of the layout viewport the keyboard hides at the bottom (iOS does not resize the
//   page for it, Android does and the value stays 0): bottom sheets sit on top of the keyboard instead of under it.
// - iOS scrolls the whole document to show a focused field and sometimes leaves it there once the keyboard
//   is gone (also after the app comes back from the background): the fixed bars then float a few pixels up
//   until the next scroll. The document itself never scrolls in this app, so it is put back at 0.
import * as React from 'react'

const FIELD = 'input:not([type=checkbox],[type=radio],[type=range],[type=button],[type=submit],[type=reset],[type=file],[type=color]), textarea, select'
const isField = (el: Element | null) => el instanceof HTMLElement && (el.matches(FIELD) || el.isContentEditable)

/** iOS Safari ignores `user-scalable=no` in a browser tab: its pinch is cancelled here (gesture events, and any
 *  move with two fingers). Android follows the viewport and `touch-action`. */
function useNoPinchZoom() {
  React.useEffect(() => {
    if (!window.matchMedia('(pointer: coarse)').matches) return
    const stop = (e: Event) => e.preventDefault()
    const twoFingers = (e: TouchEvent) => {
      if (e.touches.length > 1) e.preventDefault()
    }
    const opts = { passive: false } as const
    document.addEventListener('gesturestart', stop, opts)
    document.addEventListener('gesturechange', stop, opts)
    document.addEventListener('touchmove', twoFingers, opts)
    return () => {
      document.removeEventListener('gesturestart', stop)
      document.removeEventListener('gesturechange', stop)
      document.removeEventListener('touchmove', twoFingers)
    }
  }, [])
}

export function useMobileViewport() {
  useNoPinchZoom()
  React.useEffect(() => {
    if (!window.matchMedia('(pointer: coarse)').matches) return
    const root = document.documentElement
    const vv = window.visualViewport
    let frame = 0
    let timer = 0
    const settle = () => {
      if (!root.hasAttribute('data-kbd') && (window.scrollY || window.scrollX)) window.scrollTo(0, 0)
    }
    const measure = () => {
      frame = 0
      if (!vv) return
      const inset = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop))
      root.style.setProperty('--kbd-inset', `${inset}px`)
      root.style.setProperty('--vvh', `${Math.round(vv.height)}px`)
      if (inset < 40) settle()
    }
    const onViewport = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    const onFocusIn = (e: FocusEvent) => {
      if (!isField(e.target as Element)) return
      window.clearTimeout(timer)
      root.setAttribute('data-kbd', '')
    }
    const onFocusOut = () => {
      // The focus may jump straight to the next field: decide once it has landed.
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        if (isField(document.activeElement)) return
        root.removeAttribute('data-kbd')
        settle()
      }, 120)
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        onViewport()
        settle()
      }
    }
    measure()
    vv?.addEventListener('resize', onViewport)
    vv?.addEventListener('scroll', onViewport)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('focusout', onFocusOut)
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('pageshow', onVisible)
    window.addEventListener('orientationchange', onViewport)
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(timer)
      vv?.removeEventListener('resize', onViewport)
      vv?.removeEventListener('scroll', onViewport)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('pageshow', onVisible)
      window.removeEventListener('orientationchange', onViewport)
      root.removeAttribute('data-kbd')
    }
  }, [])
}
