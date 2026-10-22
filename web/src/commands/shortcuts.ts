// Global keyboard shortcuts. Listed in the help dialog (`?`). Pages can add their own with
// useHotkey(); add them to PAGE_SHORTCUTS docs in DESIGN.md.
import * as React from 'react'

export function isEditable(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null
  if (!e) return false
  return e.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName) || !!e.closest?.('[role="textbox"], .cm-editor')
}

/**
 * useHotkey('mod+k', handler) — `mod` = ⌘ on Mac, Ctrl elsewhere. Single keys ('?', 'shift+p') are
 * ignored while typing in a field. Sequences: 'g s' (press g then s within 1 s).
 */
export function useHotkey(combo: string, handler: (e: KeyboardEvent) => void, opts: { enabled?: boolean; allowInInput?: boolean } = {}) {
  const ref = React.useRef(handler)
  ref.current = handler
  const { enabled = true, allowInInput } = opts
  React.useEffect(() => {
    if (!enabled) return
    const steps = combo.toLowerCase().split(' ')
    let idx = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    const match = (e: KeyboardEvent, step: string) => {
      // '+' itself (zoom in): typed with Shift on most layouts, and not a separator here.
      if (step === '+') return e.key === '+' && !e.metaKey && !e.ctrlKey && !e.altKey
      const parts = step.split('+')
      const key = parts.pop()!
      const mod = parts.includes('mod')
      const shift = parts.includes('shift')
      const alt = parts.includes('alt')
      const isMod = e.metaKey || e.ctrlKey
      if (mod !== isMod) return false
      if (alt !== e.altKey) return false
      const k = e.key.toLowerCase()
      if (key === '?') return k === '?'
      if (shift !== e.shiftKey) return false
      return k === key
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing) return
      const hasMod = steps[0].includes('mod+')
      if (!allowInInput && !hasMod && isEditable(e.target)) return
      if (match(e, steps[idx])) {
        if (idx === steps.length - 1) {
          idx = 0
          clearTimeout(timer)
          e.preventDefault()
          ref.current(e)
        } else {
          idx++
          clearTimeout(timer)
          timer = setTimeout(() => (idx = 0), 1000)
        }
      } else if (idx > 0) {
        idx = 0
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      clearTimeout(timer)
    }
  }, [combo, enabled, allowInInput])
}
