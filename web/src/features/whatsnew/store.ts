// "What's new" dialog: opens once after the server version changed (per browser), or on demand
// (Settings -> System). Kept apart from the dialog so the dialog (Markdown) stays a lazy chunk.
import { create } from 'zustand'

export const SEEN_KEY = 'mx-seen-version'

export const useWhatsNew = create<{ open: boolean; since: string | null; show: (since?: string | null) => void; close: () => void }>((set) => ({
  open: false,
  since: null,
  show: (since = null) => set({ open: true, since }),
  close: () => set({ open: false }),
}))

/** Called with the running version: first visit = remember it silently; a different one = show the news. */
export function checkVersion(version: string | undefined) {
  if (!version) return
  let seen: string | null = null
  try {
    seen = localStorage.getItem(SEEN_KEY)
    if (!seen) localStorage.setItem(SEEN_KEY, version)
  } catch {
    return
  }
  if (seen && seen !== version) useWhatsNew.getState().show(seen)
}

export function markSeen(version: string) {
  try {
    localStorage.setItem(SEEN_KEY, version)
  } catch {
    /* private mode */
  }
}
