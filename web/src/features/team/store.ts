// Team: per-browser choices (the side panel open on the right of every page, its width, the chat and the tab it shows).
import { create } from 'zustand'
import { store as ls } from '@/lib/utils'

export type TeamTab = 'chats' | 'friends'
export const PANEL_W = { min: 300, max: 760, default: 380 }

const clampW = (w: number) => Math.round(Math.max(PANEL_W.min, Math.min(PANEL_W.max, w)))

type TeamUI = {
  open: boolean
  chat: string | null
  tab: TeamTab
  width: number
  setOpen: (open: boolean) => void
  setChat: (id: string | null) => void
  setTab: (tab: TeamTab) => void
  setWidth: (w: number | null) => void
}

export const useTeamUI = create<TeamUI>((set) => ({
  open: ls.get('mx-team-open') === '1',
  chat: ls.get('mx-team-chat') || null,
  tab: ls.get('mx-team-tab') === 'friends' ? 'friends' : 'chats',
  width: clampW(Number(ls.get('mx-team-width')) || PANEL_W.default),
  setOpen: (open) => {
    ls.set('mx-team-open', open ? '1' : '0')
    set({ open })
  },
  setChat: (chat) => {
    ls.set('mx-team-chat', chat || '')
    set({ chat })
  },
  setTab: (tab) => {
    ls.set('mx-team-tab', tab)
    set({ tab })
  },
  /** null = back to the default width */
  setWidth: (w) => {
    const width = w == null ? PANEL_W.default : clampW(w)
    ls.set('mx-team-width', String(width))
    set({ width })
  },
}))
