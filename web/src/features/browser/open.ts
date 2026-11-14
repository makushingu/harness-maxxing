// "Open the live view of this session's browser": asked by the link of a browser request (?browser=1, read by the
// Sessions page before it rewrites its URL) and read by the session's browser bar (SessionBrowser.tsx).
import { useSyncExternalStore } from 'react'

let wanted: string | null = null
const subs = new Set<() => void>()

export function openBrowserOf(sid: string | null) {
  wanted = sid
  subs.forEach((f) => f())
}

export function useBrowserWanted(sid: string): boolean {
  return useSyncExternalStore(
    (f) => (subs.add(f), () => subs.delete(f)),
    () => wanted === sid,
  )
}

// "Open my browser": the person's browser in its window, over any page (the sidebar's browser line, Ctrl+K,
// Settings -> Browser). One window for the whole app (MyBrowserWindow, in the shell).
let mine = false
const mineSubs = new Set<() => void>()

export function openMyBrowser(open = true) {
  mine = open
  mineSubs.forEach((f) => f())
}

export function useMyBrowserOpen(): boolean {
  return useSyncExternalStore(
    (f) => (mineSubs.add(f), () => mineSubs.delete(f)),
    () => mine,
  )
}
