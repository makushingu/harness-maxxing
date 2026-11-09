// Team: per-browser choices (Messenger-style bubbles on every page: the chat windows docked at the bottom right, the
// minimized chats as round heads, the list opened from the Team bubble, and the tab it shows).
import { create } from 'zustand'
import { store as ls } from '@/lib/utils'

export type TeamTab = 'chats' | 'friends'
/** Chat windows shown side by side at most; opening one more minimizes the oldest. */
export const MAX_WINDOWS = 3
/** Heads kept at most (the oldest go). */
const MAX_HEADS = 8

const readList = (k: string) => (ls.get(k) || '').split(',').filter(Boolean)
const save = (docked: string[], heads: string[]) => {
  ls.set('mx-team-docked', docked.join(','))
  ls.set('mx-team-heads', heads.join(','))
}

type TeamUI = {
  /** the chat list above the Team bubble */
  list: boolean
  /** open chat windows, oldest first */
  docked: string[]
  /** minimized chats, most recent first */
  heads: string[]
  tab: TeamTab
  setList: (open: boolean) => void
  openChat: (id: string) => void
  minimize: (id: string) => void
  close: (id: string) => void
  /** a new message: its chat shows up as a head (unless already on screen) */
  bump: (id: string) => void
  setTab: (tab: TeamTab) => void
}

export const useTeamUI = create<TeamUI>((set, get) => ({
  list: false,
  docked: readList('mx-team-docked').slice(-MAX_WINDOWS),
  heads: readList('mx-team-heads').slice(0, MAX_HEADS),
  tab: ls.get('mx-team-tab') === 'friends' ? 'friends' : 'chats',
  setList: (list) => set({ list }),
  openChat: (id) => {
    const s = get()
    let docked = [...s.docked.filter((x) => x !== id), id]
    let heads = s.heads.filter((x) => x !== id)
    while (docked.length > MAX_WINDOWS) heads = [docked.shift()!, ...heads]
    heads = heads.slice(0, MAX_HEADS)
    save(docked, heads)
    set({ docked, heads, list: false })
  },
  minimize: (id) => {
    const s = get()
    const docked = s.docked.filter((x) => x !== id)
    const heads = [id, ...s.heads.filter((x) => x !== id)].slice(0, MAX_HEADS)
    save(docked, heads)
    set({ docked, heads })
  },
  close: (id) => {
    const s = get()
    const docked = s.docked.filter((x) => x !== id)
    const heads = s.heads.filter((x) => x !== id)
    save(docked, heads)
    set({ docked, heads })
  },
  bump: (id) => {
    const s = get()
    if (s.docked.includes(id)) return
    const heads = [id, ...s.heads.filter((x) => x !== id)].slice(0, MAX_HEADS)
    save(s.docked, heads)
    set({ heads })
  },
  setTab: (tab) => {
    ls.set('mx-team-tab', tab)
    set({ tab })
  },
}))
