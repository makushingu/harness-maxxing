import { store as lsStore } from '@/lib/utils'
// State of the file viewer (one for the whole app): which paths it browses and where it is.
// `openFileViewer(path, list)` from anywhere; the viewer itself (Viewer.tsx) loads on first use.
import { create } from 'zustand'

type ViewerState = {
  open: boolean
  /** Paths browsed with ← / → (files or folders). */
  list: string[]
  index: number
  /** Fullscreen instead of the side panel (remembered in this browser). */
  full: boolean
  show: (path: string, list?: string[]) => void
  go: (delta: number) => void
  setList: (list: string[], index: number) => void
  setFull: (full: boolean) => void
  close: () => void
}

const FULL_KEY = 'mx-viewer-full'
/** `/a/b/` and `/a/b` are the same folder (Claude often writes folders with a final slash). */
const norm = (p: string) => p.replace(/\/+$/, '') || '/'

/** Stored "full window" choice; a browser that blocks storage (every cookie refused) must not break the app at load. */
function readFull(): boolean {
  return lsStore.get(FULL_KEY) === '1'
}

export const useFileViewer = create<ViewerState>((set, get) => ({
  open: false,
  list: [],
  index: 0,
  full: readFull(),
  show: (raw, list) => {
    const path = norm(raw)
    const l = list?.length ? [...new Set(list.map(norm))] : [path]
    const i = l.indexOf(path)
    set({ open: true, list: i < 0 ? [path] : l, index: Math.max(0, i) })
  },
  go: (delta) => {
    const { list, index } = get()
    if (list.length < 2) return
    set({ index: (index + delta + list.length) % list.length })
  },
  setList: (list, index) => set({ list: list.map(norm), index }),
  setFull: (full) => {
    lsStore.set(FULL_KEY, full ? '1' : '0')
    set({ full })
  },
  close: () => set({ open: false }),
}))

export const openFileViewer = (path: string, list?: string[]) => useFileViewer.getState().show(path, list)

/** What a conversation link to a file looks like (`#mx-file=<path>`). */
export const FILE_HREF = '#mx-file='

/** Every file of a conversation, in reading order (buttons and diagrams carry data-mx-file, answer links #mx-file=). */
export function threadFiles(thread: Element): string[] {
  const out: string[] = []
  for (const el of thread.querySelectorAll<HTMLElement>(`[data-mx-file], a[href^="${FILE_HREF}"]`)) {
    const p = el.dataset.mxFile ?? decodeURIComponent((el.getAttribute('href') || '').slice(FILE_HREF.length))
    if (p && !out.includes(p)) out.push(p)
  }
  return out
}
