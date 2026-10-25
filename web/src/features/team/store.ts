// Team: per-browser choices (the side panel open on the right of every page, the chat it shows).
import { create } from 'zustand'
import { store as ls } from '@/lib/utils'

type TeamUI = {
  open: boolean
  chat: string | null
  setOpen: (open: boolean) => void
  setChat: (id: string | null) => void
}

export const useTeamUI = create<TeamUI>((set) => ({
  open: ls.get('mx-team-open') === '1',
  chat: ls.get('mx-team-chat') || null,
  setOpen: (open) => {
    ls.set('mx-team-open', open ? '1' : '0')
    set({ open })
  },
  setChat: (chat) => {
    ls.set('mx-team-chat', chat || '')
    set({ chat })
  },
}))
