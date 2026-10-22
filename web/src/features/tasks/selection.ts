// Multi-selection of tasks (board and list) for bulk actions. Cleared when leaving the Tasks page.
import { create } from 'zustand'

type State = {
  ids: Set<string>
  toggle: (id: string) => void
  add: (ids: string[]) => void
  remove: (ids: string[]) => void
  clear: () => void
}

export const useTaskSelection = create<State>((set) => ({
  ids: new Set(),
  toggle: (id) =>
    set((s) => {
      const ids = new Set(s.ids)
      if (ids.has(id)) ids.delete(id)
      else ids.add(id)
      return { ids }
    }),
  add: (list) => set((s) => ({ ids: new Set([...s.ids, ...list]) })),
  remove: (list) =>
    set((s) => {
      const ids = new Set(s.ids)
      for (const id of list) ids.delete(id)
      return { ids }
    }),
  clear: () => set((s) => (s.ids.size ? { ids: new Set() } : s)),
}))

/** A click that should select instead of open: modifier keys, or a selection already in progress. */
export function isSelectClick(e: { metaKey: boolean; ctrlKey: boolean; shiftKey: boolean }): boolean {
  return e.metaKey || e.ctrlKey || e.shiftKey || useTaskSelection.getState().ids.size > 0
}
