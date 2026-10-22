// Text zoom (markdown preview + text editor, saved in this browser) and the reading position of each text file:
// where you were in it, so switching Preview / Edit / Split or opening the file again lands on the same place.
// No React here: also used by the lazy CodeMirror chunk.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const TEXT_ZOOMS = [0.75, 0.85, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5] as const

type ZoomState = { zoom: number; setZoom: (z: number) => void; step: (dir: 1 | -1) => void }

const nearest = (z: number) => TEXT_ZOOMS.reduce((a, b) => (Math.abs(b - z) < Math.abs(a - z) ? b : a), 1 as number)

export const useTextZoom = create<ZoomState>()(
  persist(
    (set, get) => ({
      zoom: 1,
      setZoom: (z) => set({ zoom: nearest(z) }),
      step: (dir) => {
        const i = TEXT_ZOOMS.indexOf(nearest(get().zoom) as (typeof TEXT_ZOOMS)[number])
        set({ zoom: TEXT_ZOOMS[Math.max(0, Math.min(TEXT_ZOOMS.length - 1, i + dir))] })
      },
    }),
    { name: 'mx-text-zoom', partialize: (s) => ({ zoom: s.zoom }), merge: (p, c) => ({ ...c, zoom: nearest(Number((p as Partial<ZoomState>)?.zoom) || 1) }) },
  ),
)

/**
 * Where the top of the view is. `view` says which one wrote it: the same view restores it exactly (`line` for the
 * editor, `block` = index of the top block of the rendered page + how far into it), the other one goes through the
 * markdown headings (`h` = index of the heading above, `within` = how far towards the next one), else `frac`.
 */
export type ReadPos = { view: 'src' | 'md'; frac: number; line?: number; block?: { i: number; r: number }; h?: { i: number; within: number } }

const KEY = 'mx-read-pos'
const MAX = 100
let cache: Map<string, ReadPos & { at: number }> | null = null
let timer: ReturnType<typeof setTimeout> | null = null

const int = (n: unknown) => Number.isInteger(n) && (n as number) >= 0
const num = (n: unknown) => typeof n === 'number' && Number.isFinite(n)

/** A position read back from storage (edited by hand, an older version…): every field checked, or dropped. */
export function validReadPos(v: unknown): v is ReadPos {
  if (!v || typeof v !== 'object') return false
  const p = v as Partial<ReadPos>
  if ((p.view !== 'src' && p.view !== 'md') || !num(p.frac)) return false
  if (p.line !== undefined && !(int(p.line) && p.line > 0)) return false
  if (p.block !== undefined && !(p.block && typeof p.block === 'object' && int(p.block.i) && num(p.block.r))) return false
  if (p.h !== undefined && !(p.h && typeof p.h === 'object' && int(p.h.i) && num(p.h.within))) return false
  return true
}

function load() {
  if (cache) return cache
  cache = new Map()
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}')
    if (raw && typeof raw === 'object') for (const [k, v] of Object.entries(raw)) if (validReadPos(v)) cache.set(k, v as ReadPos & { at: number })
  } catch {
    /* unreadable storage: start empty */
  }
  return cache
}

export function getReadPos(path: string): ReadPos | null {
  return load().get(path) ?? null
}

export function setReadPos(path: string, pos: ReadPos) {
  const m = load()
  m.delete(path)
  m.set(path, { ...pos, at: Date.now() })
  while (m.size > MAX) m.delete(m.keys().next().value!)
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(m)))
    } catch {
      /* full or private mode: the position stays for this tab */
    }
  }, 400)
}

/** 1-based line numbers of the markdown headings (ATX `#`, outside fenced code), in order. */
export function sourceHeadings(text: string): number[] {
  const out: number[] = []
  let fence: string | null = null
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    const f = /^ {0,3}(`{3,}|~{3,})/.exec(l)
    if (f) {
      if (!fence) fence = f[1][0]
      else if (f[1][0] === fence) fence = null
      continue
    }
    if (!fence && /^ {0,3}#{1,6}(\s|$)/.test(l)) out.push(i + 1)
  }
  return out
}

/** Heading index + progress towards the next heading for a position given in the same unit as `starts`. */
export function headingAt(starts: number[], at: number, end: number): ReadPos['h'] {
  let i = -1
  for (let k = 0; k < starts.length && starts[k] <= at; k++) i = k
  if (i < 0) return undefined
  const from = starts[i]
  const to = i + 1 < starts.length ? starts[i + 1] : end
  return { i, within: to > from ? Math.min(1, Math.max(0, (at - from) / (to - from))) : 0 }
}

/** The inverse: a position in the unit of `starts` (null when the heading does not exist there). */
export function fromHeading(starts: number[], h: NonNullable<ReadPos['h']>, end: number): number | null {
  if (h.i >= starts.length) return null
  const from = starts[h.i]
  const to = h.i + 1 < starts.length ? starts[h.i + 1] : end
  return from + h.within * (to - from)
}
