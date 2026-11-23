// Open state of the Feedback dialog (sidebar button, touch drawer, command palette) and of the shortcuts dialog. Kept
// apart from FeedbackDialog.tsx / ShortcutsDialog.tsx so the dialogs themselves can be lazy chunks.
import { create } from 'zustand'

type OpenState = { open: boolean; setOpen: (o: boolean) => void }
const openStore = () => create<OpenState>((set) => ({ open: false, setOpen: (open) => set({ open }) }))

export const useFeedbackDialog = openStore()
export const useShortcutsDialog = openStore()
