// Which terminals each session shows in its drawer (this browser): the server only knows the terminals themselves.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Drawer = { open: boolean; ids: string[]; active?: string; height?: number }

type TermUI = {
  bySid: Record<string, Drawer>
  toggle: (sid: string, open?: boolean) => void
  add: (sid: string, id: string) => void
  remove: (id: string) => void
  setActive: (sid: string, id: string) => void
  setHeight: (sid: string, h: number) => void
  /** Drops the ids the server no longer has (closed elsewhere, server restarted). */
  keepOnly: (alive: string[]) => void
}

const empty: Drawer = { open: false, ids: [] }

export const useTermUI = create<TermUI>()(
  persist(
    (set) => ({
      bySid: {},
      toggle: (sid, open) => set((s) => ({ bySid: { ...s.bySid, [sid]: { ...(s.bySid[sid] ?? empty), open: open ?? !s.bySid[sid]?.open } } })),
      add: (sid, id) => set((s) => {
        const d = s.bySid[sid] ?? empty
        return { bySid: { ...s.bySid, [sid]: { ...d, open: true, ids: [...d.ids.filter((x) => x !== id), id], active: id } } }
      }),
      remove: (id) => set((s) => {
        const bySid: Record<string, Drawer> = {}
        for (const [k, d] of Object.entries(s.bySid)) {
          const ids = d.ids.filter((x) => x !== id)
          bySid[k] = { ...d, ids, active: d.active === id ? ids[ids.length - 1] : d.active }
        }
        return { bySid }
      }),
      setActive: (sid, id) => set((s) => ({ bySid: { ...s.bySid, [sid]: { ...(s.bySid[sid] ?? empty), active: id } } })),
      setHeight: (sid, h) => set((s) => ({ bySid: { ...s.bySid, [sid]: { ...(s.bySid[sid] ?? empty), height: h } } })),
      keepOnly: (alive) => set((s) => {
        const keep = new Set(alive)
        const bySid: Record<string, Drawer> = {}
        for (const [k, d] of Object.entries(s.bySid)) {
          const ids = d.ids.filter((x) => keep.has(x))
          if (ids.length || d.open) bySid[k] = { ...d, ids, active: d.active && keep.has(d.active) ? d.active : ids[ids.length - 1] }
        }
        return { bySid }
      }),
    }),
    { name: 'mx-terminals', version: 1 },
  ),
)
