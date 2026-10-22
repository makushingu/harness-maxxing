// Open state of the shortcuts dialog. Kept apart from ShortcutsDialog.tsx so the dialog itself can be a lazy chunk.
import { create } from 'zustand'

export const useShortcutsDialog = create<{ open: boolean; setOpen: (o: boolean) => void }>((set) => ({ open: false, setOpen: (open) => set({ open }) }))
