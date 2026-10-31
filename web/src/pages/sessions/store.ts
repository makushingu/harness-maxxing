// Sessions page state (persisted per browser): open columns, widths, focus, tree folding.
// Columns have a stable `key` so a "new session" column that becomes a real session keeps its
// React identity (no remount flash) — only `kind`/`id` change.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { arrange, type Slot } from './layouts'

/** What the sessions list is grouped by: `project` (projects > topics > sessions) or `session` (only the
 *  sessions, each labelled with its project › topic, most used first by default). */
export type ListBy = 'project' | 'session'
/** Layout of the `project` list: `tree` (foldable), `drill` (one level at a time). */
export type TreeMode = 'tree' | 'drill'
export const TREE_MODES: TreeMode[] = ['tree', 'drill']
/** `used`: most used lately (turns, faded by the age of the last activity). */
export type FlatSort = 'used' | 'recent' | 'name' | 'created'
export const FLAT_SORTS: FlatSort[] = ['used', 'recent', 'name', 'created']
export const RECENT_COUNTS = [3, 5, 10, 20]

/** `below`: the column sits under the one before it (two sessions share a column of the strip: 2x2 grid).
 *  `wide`: without a set width, its column of the strip takes two shares of the room instead of one. */
export type Col = ({ key: string; kind: 'session'; id: string } | { key: string; kind: 'new'; path: string }) & { below?: boolean; wide?: boolean }

/** At most two sessions per column of the strip: the first column is never `below`, and a `below` column always
 *  follows one that is not. */
export function normalizeCols(cols: Col[]): Col[] {
  let changed = false
  const out = cols.map((c, i) => {
    const prev = cols[i - 1]
    if (c.below && c.wide) {
      changed = true
      const { wide: _w, ...rest } = c
      return rest as Col
    }
    const ok = !c.below || (i > 0 && !prev.below)
    if (ok) return c
    changed = true
    const { below: _b, ...rest } = c
    return rest as Col
  })
  // a fix can make the next one valid again: run until stable
  return changed ? normalizeCols(out) : cols
}

/** `cols` without `key`; when `key` was the top of a pair, the session under it gets its own column (else it would
 *  slide under whatever column comes before). */
function detach(cols: Col[], key: string): Col[] {
  const i = cols.findIndex((c) => c.key === key)
  if (i < 0) return cols
  const out = cols.filter((c) => c.key !== key)
  const next = cols[i + 1]
  if (!cols[i].below && next?.below) out[i] = (({ below: _b, ...r }) => r as Col)(next)
  return out
}

/** Index range [start, end] of the strip column (one session or a pair) that holds `cols[i]`. */
function groupAt(cols: Col[], i: number): [number, number] {
  const start = cols[i]?.below ? i - 1 : i
  return [start, cols[start + 1]?.below ? start + 1 : start]
}

/** Whether `key` can move one strip column to the left (-1) or right (+1): a session of a pair always can (it leaves
 *  the pair on that side). */
export function canShift(cols: Col[], key: string, dir: -1 | 1): boolean {
  const i = cols.findIndex((c) => c.key === key)
  if (i < 0) return false
  if (cols[i].below || cols[i + 1]?.below) return true
  return dir < 0 ? i > 0 : i < cols.length - 1
}

export const ROW_SPLIT_MIN = 0.2
export const ROW_SPLIT_MAX = 0.8

type State = {
  cols: Col[]
  focused: string | null
  /** Column width in px by column key (absent = flexible). */
  widths: Record<string, number>
  /** Share of the height given to the top session where two share a column (0.2-0.8). */
  rowSplit: number
  /** Tree node expanded flags: `p:<project>`, `t:<topic path>`, `a:<topic path>` (archived fold). */
  expanded: Record<string, boolean>
  treeHidden: boolean
  listBy: ListBy
  treeMode: TreeMode
  /** Where the `drill` layout is: projects (both null), a project's topics, or a topic's sessions. */
  drill: { project: string | null; topic: string | null }
  flatSort: FlatSort
  /** Sort direction of the `flat` layout (true = newest / Z first). */
  flatDesc: boolean
  showFavorites: boolean
  showRecent: boolean
  recentCount: number
  setListBy: (by: ListBy) => void
  setTreeMode: (m: TreeMode) => void
  setDrill: (d: { project: string | null; topic: string | null }) => void
  setFlatSort: (sort: FlatSort, desc?: boolean) => void
  setBlocks: (b: Partial<Pick<State, 'showFavorites' | 'showRecent' | 'recentCount'>>) => void
  /** Tree shows only these sessions (a badge was clicked); not persisted. */
  show: SessionShow | null
  setShow: (show: SessionShow | null) => void
  /** Rows folded by hand while a filter (search, running / unread) unfolds the tree; cleared when the filter changes. */
  narrowFolded: Record<string, boolean>
  setNarrowFolded: (nodes: Record<string, boolean>) => void
  /** Column whose layouts picker was opened from its menu (keyboard); not persisted. */
  layoutPicker: string | null
  setLayoutPicker: (key: string | null) => void
  /** Column being dragged by its grip (the layouts bar shows at the top); not persisted. */
  dragging: string | null
  setDragging: (key: string | null) => void
  openSession: (id: string, opts?: { focus?: boolean; after?: string | null }) => string
  openNew: (path: string) => string
  close: (key: string) => void
  closeSession: (id: string) => void
  becomeSession: (key: string, id: string) => void
  setNewPath: (key: string, path: string) => void
  focus: (key: string | null) => void
  move: (key: string, toIndex: number) => void
  /** Put `key` in its own strip column just left or right of the strip column holding `target`. */
  moveBeside: (key: string, target: string, side: 'left' | 'right') => void
  /** One strip column to the left / right (out of its pair first when it is stacked). */
  shift: (key: string, dir: -1 | 1) => void
  setWidth: (key: string, w: number | null) => void
  setRowSplit: (v: number) => void
  /** Put column `key` under column `under` (which must be alone in its column). */
  stack: (key: string, under: string) => void
  /** Put column `key` above column `over` (which must be alone in its column): `key` takes its place, `over` goes under. */
  stackAbove: (key: string, over: string) => void
  /** Give a stacked session its own column again. */
  unstack: (key: string) => void
  /** 2x2: every second column goes under the one before it. */
  toGrid: () => void
  /** Back to one session per column. */
  toColumns: () => void
  /** A ready-made layout (`arrange`); widths go back to even shares. */
  applyLayout: (slots: Slot[], move?: { key: string; zone: number }) => void
  /** Maxxing mode: session `id` alone on the strip (its column kept if it is open); returns its column key. */
  solo: (id: string) => string
  /** Put back a saved arrangement (Maxxing mode off), plus the session on screen if it was not in it. */
  restoreLayout: (saved: { cols: Col[]; widths: Record<string, number> }) => void
  toggle: (node: string, value?: boolean) => void
  /** Set many tree nodes at once (expand / collapse all). */
  setExpanded: (nodes: Record<string, boolean>) => void
  setTreeHidden: (v: boolean) => void
  /** Tabs view: one session on screen, the open ones as chips above it (the columns stay as they are). */
  tabs: boolean
  setTabs: (v: boolean) => void
}

export type SessionShow = 'running' | 'unread'

const uid = () => Math.random().toString(36).slice(2, 10)

export const useSessionsUI = create<State>()(
  persist(
    (set, get) => ({
      cols: [],
      focused: null,
      widths: {},
      rowSplit: 0.5,
      expanded: {},
      treeHidden: false,
      listBy: 'project',
      treeMode: 'tree',
      drill: { project: null, topic: null },
      flatSort: 'used',
      flatDesc: true,
      showFavorites: true,
      showRecent: false,
      recentCount: 5,
      setListBy: (listBy) => set({ listBy }),
      setTreeMode: (treeMode) => set({ treeMode }),
      setDrill: (drill) => set({ drill }),
      // A new criterion starts in its natural direction: newest first for dates, A to Z for names.
      setFlatSort: (flatSort, desc) => set({ flatSort, flatDesc: desc ?? flatSort !== 'name' }),
      setBlocks: (b) => set(b),
      openSession: (id, opts = {}) => {
        const { focus = true } = opts
        const existing = get().cols.find((c) => c.kind === 'session' && c.id === id)
        if (existing) {
          if (focus) set({ focused: existing.key })
          return existing.key
        }
        const col: Col = { key: uid(), kind: 'session', id }
        set((s) => {
          const cols = [...s.cols]
          const at = opts.after ? cols.findIndex((c) => c.key === opts.after) : -1
          if (at >= 0) cols.splice(at + 1, 0, col)
          else cols.push(col)
          return { cols, focused: focus ? col.key : s.focused }
        })
        return col.key
      },
      openNew: (path) => {
        // Reuse an untouched "new" column of the same topic instead of stacking duplicates.
        const existing = get().cols.find((c) => c.kind === 'new' && c.path === path)
        if (existing) {
          set({ focused: existing.key })
          return existing.key
        }
        const col: Col = { key: uid(), kind: 'new', path }
        set((s) => ({ cols: [...s.cols, col], focused: col.key }))
        return col.key
      },
      close: (key) =>
        set((s) => {
          const i = s.cols.findIndex((c) => c.key === key)
          if (i < 0) return s
          const cols = normalizeCols(detach(s.cols, key))
          const { [key]: _w, ...widths } = s.widths
          let focused = s.focused
          if (focused === key) focused = cols[Math.min(i, cols.length - 1)]?.key ?? null
          return { cols, widths, focused }
        }),
      closeSession: (id) => {
        const c = get().cols.find((x) => x.kind === 'session' && x.id === id)
        if (c) get().close(c.key)
      },
      becomeSession: (key, id) =>
        set((s) => {
          // If that session is somehow already open elsewhere, drop the duplicate.
          const dup = s.cols.find((c) => c.kind === 'session' && c.id === id && c.key !== key)
          const cols = normalizeCols(s.cols.filter((c) => c !== dup).map((c) => (c.key === key ? ({ key, kind: 'session', id, ...(c.below && { below: true }), ...(c.wide && { wide: true }) } as Col) : c)))
          return { cols }
        }),
      setNewPath: (key, path) => set((s) => ({ cols: s.cols.map((c) => (c.key === key && c.kind === 'new' ? { ...c, path } : c)) })),
      focus: (key) => {
        if (get().focused !== key) set({ focused: key })
      },
      move: (key, toIndex) =>
        set((s) => {
          const from = s.cols.findIndex((c) => c.key === key)
          if (from < 0) return s
          const { below: _b, ...moved } = s.cols[from]   // a moved session gets its own column
          const cols = detach(s.cols, key)
          let to = Math.max(0, Math.min(cols.length, toIndex))
          if (cols[to]?.below) to += to >= from ? 1 : -1    // never between a pair
          cols.splice(Math.max(0, to), 0, moved as Col)
          return { cols: normalizeCols(cols) }
        }),
      moveBeside: (key, target, side) =>
        set((s) => {
          const c = s.cols.find((x) => x.key === key)
          if (!c || key === target) return s
          const cols = detach(s.cols, key)
          const ti = cols.findIndex((x) => x.key === target)
          if (ti < 0) return s
          const [start, end] = groupAt(cols, ti)
          const { below: _b, ...moved } = c
          cols.splice(side === 'left' ? start : end + 1, 0, moved as Col)
          return { cols: normalizeCols(cols) }
        }),
      shift: (key, dir) => {
        const cols = get().cols
        const i = cols.findIndex((c) => c.key === key)
        if (i < 0 || !canShift(cols, key, dir)) return
        const side = dir < 0 ? 'left' : 'right'
        // in a pair: out of it, on that side of its partner
        if (cols[i].below) return get().moveBeside(key, cols[i - 1].key, side)
        if (cols[i + 1]?.below) return get().moveBeside(key, cols[i + 1].key, side)
        // alone: past the neighbouring strip column (a whole pair counts as one)
        const neighbour = dir < 0 ? groupAt(cols, i - 1)[0] : i + 1
        get().moveBeside(key, cols[neighbour].key, side)
      },
      setRowSplit: (v) => set({ rowSplit: Math.max(ROW_SPLIT_MIN, Math.min(ROW_SPLIT_MAX, v)) }),
      stack: (key, under) =>
        set((s) => {
          const target = s.cols.findIndex((c) => c.key === under)
          const t = s.cols[target]
          if (!t || key === under || t.below || s.cols[target + 1]?.below) return s
          const moving = s.cols.find((c) => c.key === key)
          if (!moving) return s
          const { wide: _w, ...m } = moving
          const cols = detach(s.cols, key)
          cols.splice(cols.findIndex((c) => c.key === under) + 1, 0, { ...m, below: true } as Col)
          return { cols: normalizeCols(cols), focused: key }
        }),
      stackAbove: (key, over) =>
        set((s) => {
          const target = s.cols.findIndex((c) => c.key === over)
          const t = s.cols[target]
          if (!t || key === over || t.below || s.cols[target + 1]?.below) return s
          const moving = s.cols.find((c) => c.key === key)
          if (!moving) return s
          const { wide: _w, below: _b, ...m } = moving
          const { wide, ...under } = t
          const cols = detach(s.cols, key)
          // `key` takes the strip column of `over` (its `wide` and saved width, kept under the top key) and `over` goes under it
          cols.splice(cols.findIndex((c) => c.key === over), 1, { ...m, ...(wide && { wide: true }) } as Col, { ...under, below: true } as Col)
          const { [key]: _old, [over]: w, ...widths } = s.widths
          return { cols: normalizeCols(cols), widths: w == null ? widths : { ...widths, [key]: w }, focused: key }
        }),
      unstack: (key) => set((s) => ({ cols: normalizeCols(s.cols.map((c) => (c.key === key ? (({ below: _b, ...r }) => r as Col)(c) : c))) })),
      toGrid: () => set((s) => ({ cols: normalizeCols(s.cols.map((c, i) => (i % 2 ? { ...c, below: true } : (({ below: _b, ...r }) => r as Col)(c)))) })),
      toColumns: () => set((s) => ({ cols: s.cols.map((c) => (({ below: _b, ...r }) => r as Col)(c)) })),
      applyLayout: (slots, move) =>
        set((s) => ({ cols: arrange(s.cols, slots, move), widths: {}, focused: move?.key ?? s.focused })),
      solo: (id) => {
        const { cols, focused } = get()
        // the column on screen is reused (same key: its place stays, only the session in it changes); else the
        // session's own column, else a new one
        const keep = cols.length === 1 ? cols[0] : cols.find((x) => x.kind === 'session' && x.id === id) || cols.find((x) => x.key === focused)
        const col: Col = { key: keep?.key ?? uid(), kind: 'session', id }
        set({ cols: [col], focused: col.key })
        return col.key
      },
      restoreLayout: (saved) =>
        set((s) => {
          const ids = new Set(saved.cols.flatMap((c) => (c.kind === 'session' ? [c.id] : [])))
          const keys = new Set(saved.cols.map((c) => c.key))
          const extra = s.cols.filter((c) => !keys.has(c.key) && !(c.kind === 'session' && ids.has(c.id))).map(({ below: _b, wide: _w, ...r }) => r as Col)
          const cols = normalizeCols([...saved.cols, ...extra])
          const cur = s.cols.find((c) => c.key === s.focused)
          const focused = cols.find((c) => c.key === s.focused || (cur?.kind === 'session' && c.kind === 'session' && c.id === cur.id))?.key ?? cols[0]?.key ?? null
          return { cols, widths: saved.widths, focused }
        }),
      setWidth: (key, w) =>
        set((s) => {
          const { [key]: _old, ...rest } = s.widths
          return { widths: w == null ? rest : { ...rest, [key]: Math.round(w) } }
        }),
      toggle: (node, value) => set((s) => ({ expanded: { ...s.expanded, [node]: value ?? !s.expanded[node] } })),
      setExpanded: (nodes) => set((s) => ({ expanded: { ...s.expanded, ...nodes } })),
      setTreeHidden: (treeHidden) => set({ treeHidden }),
      tabs: false,
      setTabs: (tabs) => set({ tabs }),
      show: null,
      setShow: (show) => set({ show }),
      narrowFolded: {},
      setNarrowFolded: (narrowFolded) => set({ narrowFolded }),
      layoutPicker: null,
      setLayoutPicker: (layoutPicker) => set({ layoutPicker }),
      dragging: null,
      setDragging: (dragging) => set({ dragging }),
    }),
    {
      name: 'mx-sessions',
      version: 2,
      // v1 had a third layout, `flat` (sessions only): it became the `session` list, most used first.
      migrate: (persisted, version) => {
        const p = (persisted || {}) as Record<string, unknown>
        if (version < 2) {
          if (p.treeMode === 'flat') Object.assign(p, { listBy: 'session', treeMode: 'tree' })
          p.flatSort = 'used'
        }
        return p as unknown as State
      },
      partialize: (s) => ({
        cols: s.cols,
        focused: s.focused,
        widths: s.widths,
        rowSplit: s.rowSplit,
        expanded: s.expanded,
        treeHidden: s.treeHidden,
        tabs: s.tabs,
        listBy: s.listBy,
        treeMode: s.treeMode,
        drill: s.drill,
        flatSort: s.flatSort,
        flatDesc: s.flatDesc,
        showFavorites: s.showFavorites,
        showRecent: s.showRecent,
        recentCount: s.recentCount,
      }),
      // Unknown values (older or edited storage) fall back to the defaults.
      merge: (persisted, current) => {
        const p = { ...current, ...(persisted as Partial<State>) }
        if (p.listBy !== 'session') p.listBy = 'project'
        p.cols = normalizeCols(Array.isArray(p.cols) ? p.cols : [])
        if (typeof p.rowSplit !== 'number' || !(p.rowSplit >= ROW_SPLIT_MIN && p.rowSplit <= ROW_SPLIT_MAX)) p.rowSplit = 0.5
        if (!TREE_MODES.includes(p.treeMode)) p.treeMode = 'tree'
        if (!FLAT_SORTS.includes(p.flatSort)) p.flatSort = 'used'
        p.flatDesc = p.flatSort !== 'name'             // no reverse button: always the natural order
        if (!RECENT_COUNTS.includes(p.recentCount)) p.recentCount = 5
        if (!p.drill || typeof p.drill !== 'object') p.drill = { project: null, topic: null }
        return p
      },
    },
  ),
)

/* ---------------------------------------------------------------- Local "pending" messages
 * Messages sent from this tab that are not in the log yet: shown as an optimistic bubble (sent while
 * idle) or in the queue stack (sent while running), removed when the matching `user` event arrives. */
export type Pending = { lid: string; text: string; attachments: string[]; queued: boolean; at: number; /** A voice message being sent. */ voice?: boolean }

type PendingState = {
  bySession: Record<string, Pending[]>
  add: (sid: string, p: Omit<Pending, 'lid' | 'at'>) => string
  remove: (sid: string, lid: string) => void
  /** A `user` event arrived: drop the first pending with the same text. */
  settle: (sid: string, text: string) => void
  clearQueued: (sid: string) => void
  trimQueued: (sid: string, keep: number) => void
}

export const usePending = create<PendingState>((set) => ({
  bySession: {},
  add: (sid, p) => {
    const lid = uid()
    set((s) => ({ bySession: { ...s.bySession, [sid]: [...(s.bySession[sid] || []), { ...p, lid, at: Date.now() }] } }))
    return lid
  },
  remove: (sid, lid) => set((s) => ({ bySession: { ...s.bySession, [sid]: (s.bySession[sid] || []).filter((p) => p.lid !== lid) } })),
  settle: (sid, text) =>
    set((s) => {
      const list = s.bySession[sid]
      if (!list?.length) return s
      const norm = text.trim()
      const i = list.findIndex((p) => p.text.trim() === norm)
      if (i < 0) return s
      return { bySession: { ...s.bySession, [sid]: list.filter((_, j) => j !== i) } }
    }),
  clearQueued: (sid) => set((s) => ({ bySession: { ...s.bySession, [sid]: (s.bySession[sid] || []).filter((p) => !p.queued) } })),
  trimQueued: (sid, keep) =>
    set((s) => {
      const list = s.bySession[sid] || []
      const queued = list.filter((p) => p.queued)
      if (queued.length <= keep) return s
      const drop = new Set(queued.slice(0, queued.length - keep).map((p) => p.lid))
      return { bySession: { ...s.bySession, [sid]: list.filter((p) => !drop.has(p.lid)) } }
    }),
}))

const EMPTY: Pending[] = []
export const usePendingFor = (sid: string | null) => usePending((s) => (sid ? s.bySession[sid] || EMPTY : EMPTY))

/* ---------------------------------------------------------------- Drafts (localStorage) */
const draftKey = (k: string) => `mx-draft:${k}`
export function loadDraft(k: string): string {
  try {
    return localStorage.getItem(draftKey(k)) || ''
  } catch {
    return ''
  }
}
/** Fired with the draft key when a draft is written from outside its composer (prefillDraft): a mounted composer reloads it. */
export const DRAFT_EVENT = 'mx-draft'
const PREFILL = 'mx-prefilled:'

/** Types `prompt` in a composer's draft (links such as the dashboard examples). A draft that is still an untouched
 *  earlier prefill is replaced; text the user wrote is kept, the prompt goes after it. */
export function prefillDraft(k: string, prompt: string) {
  const cur = loadDraft(k).trim()
  let prev = ''
  try {
    prev = localStorage.getItem(PREFILL + k) || ''
  } catch {
    /* private mode */
  }
  if (cur === prompt.trim()) return
  saveDraft(k, !cur || cur === prev.trim() ? prompt : `${cur}\n\n${prompt}`)
  try {
    localStorage.setItem(PREFILL + k, prompt)
  } catch {
    /* quota / private mode */
  }
  window.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: k }))
}

export function saveDraft(k: string, text: string) {
  try {
    if (text) localStorage.setItem(draftKey(k), text)
    else localStorage.removeItem(draftKey(k))
  } catch {
    /* quota / private mode */
  }
}

// Quotes waiting in the composer (Quote on a selected reply): kept with the draft, under their own key.
export function loadQuotes(k: string): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(`${draftKey(k)}:quotes`) || '[]')
    return Array.isArray(v) ? v.filter((q) => typeof q === 'string' && q) : []
  } catch {
    return []
  }
}
export function saveQuotes(k: string, quotes: string[]) {
  try {
    if (quotes.length) localStorage.setItem(`${draftKey(k)}:quotes`, JSON.stringify(quotes))
    else localStorage.removeItem(`${draftKey(k)}:quotes`)
  } catch {
    /* quota / private mode */
  }
}

/* ---------------------------------------------------------------- Seeds (a message brought back into a composer) */
/** What a message puts back in a composer: Edit on a stopped message, "New session from this message". */
export type Seed = { text: string; quotes: string[]; attachments: string[] }
const SEED_EVENT = 'mx-seed'
const seeds = new Map<string, Seed>()
/** Hands `seed` to the composer of draft `k`: applied at once if it is open, else when it mounts. */
export function seedComposer(k: string, seed: Seed) {
  seeds.set(k, seed)
  window.dispatchEvent(new CustomEvent(SEED_EVENT, { detail: k }))
}
/** The seed waiting for draft `k`, taken once. */
export function takeSeed(k: string): Seed | null {
  const s = seeds.get(k) ?? null
  seeds.delete(k)
  return s
}
export function onSeed(k: string, fn: (s: Seed) => void): () => void {
  const on = (e: Event) => {
    if ((e as CustomEvent<string>).detail !== k) return
    const s = takeSeed(k)
    if (s) fn(s)
  }
  window.addEventListener(SEED_EVENT, on)
  return () => window.removeEventListener(SEED_EVENT, on)
}

/* ---------------------------------------------------------------- Composer registry (focus by column) */
const composers = new Map<string, HTMLTextAreaElement>()
export function registerComposer(key: string, el: HTMLTextAreaElement | null) {
  if (el) composers.set(key, el)
  else composers.delete(key)
}
export function focusComposer(key: string | null) {
  if (!key) return false
  const el = composers.get(key)
  if (!el) return false
  el.focus({ preventScroll: true })
  el.closest('[data-col]')?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
  return true
}
