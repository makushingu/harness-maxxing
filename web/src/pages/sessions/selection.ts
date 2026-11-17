// Several sessions picked in the tree (computer): a click sets the starting row, Ctrl (Cmd) or Shift + click on
// another row picks every session in between (same topic, project, or across them, as shown); Ctrl + click on a
// topic or a project picks all its sessions. The bar above the list then opens, closes, archives or deletes them.
import { create } from 'zustand'
import { loadGroups } from '@/i18n'

type Sel = { ids: string[]; anchor: string | null }
export const useSessionSelection = create<Sel>(() => ({ ids: [], anchor: null }))

/** A plain click: the row is where the next Ctrl + click starts; nothing stays picked. */
export function setAnchor(id: string) {
  const s = useSessionSelection.getState()
  if (s.anchor !== id || s.ids.length) useSessionSelection.setState({ anchor: id, ids: [] })
}

export function clearSelection() {
  useSessionSelection.setState({ ids: [] })
}

const rowsOf = (from: HTMLElement) =>
  [...(from.closest('[role="tree"]') ?? document).querySelectorAll<HTMLElement>('[data-session-row]')].map((el) => el.dataset.sessionRow!)

/** Ctrl / Shift + click on a session row: every row from the starting one to this one, in the order shown. */
export async function pickRange(id: string, from: HTMLElement) {
  await loadGroups(['sel'])
  const { anchor } = useSessionSelection.getState()
  const rows = rowsOf(from)
  const to = rows.indexOf(id)
  // The starting row may be shown twice (Favorites and its topic): the copy nearest to the clicked row.
  let at = -1
  rows.forEach((r, i) => {
    if (r === anchor && (at < 0 || Math.abs(i - to) < Math.abs(at - to))) at = i
  })
  if (at < 0 || to < 0) {
    useSessionSelection.setState({ anchor: id, ids: [id] })
    return
  }
  const [a, b] = at < to ? [at, to] : [to, at]
  useSessionSelection.setState({ ids: [...new Set(rows.slice(a, b + 1))] })
}

/** Ctrl + click on a topic or a project: all its sessions, or none when they were all picked already. */
export async function pickAll(ids: string[]) {
  if (!ids.length) return
  await loadGroups(['sel'])
  const cur = useSessionSelection.getState().ids
  const all = ids.every((id) => cur.includes(id))
  useSessionSelection.setState({ ids: all ? cur.filter((id) => !ids.includes(id)) : [...new Set([...cur, ...ids])] })
}

export const withModifier = (e: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) => e.ctrlKey || e.metaKey || e.shiftKey
