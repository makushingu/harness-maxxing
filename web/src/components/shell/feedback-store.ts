// Open state of the Feedback dialog (sidebar button, touch drawer, command palette). Kept apart from
// FeedbackDialog.tsx so the dialog itself can be a lazy chunk.
import { create } from 'zustand'

export const useFeedbackDialog = create<{ open: boolean; setOpen: (o: boolean) => void }>((set) => ({ open: false, setOpen: (open) => set({ open }) }))
