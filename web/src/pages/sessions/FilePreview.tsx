// Paths clicked in a conversation open the app's file viewer. ← / → then browse every file shown in
// the same thread (attachments, media, files Claude read or wrote, paths in its answers), in order.
import * as React from 'react'
import { openFileViewer, threadFiles } from '@/features/files/viewerStore'

const PreviewCtx = React.createContext<(path: string) => void>(() => {})
export const useOpenPreview = () => React.useContext(PreviewCtx)

export function PreviewProvider({ children }: { children: React.ReactNode }) {
  const last = React.useRef<Element | null>(null)
  React.useEffect(() => {
    const onDown = (e: Event) => (last.current = e.target as Element)
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onDown, true)
    return () => {
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('keydown', onDown, true)
    }
  }, [])
  const show = React.useCallback((p: string) => {
    const thread = last.current?.closest?.('[data-thread]') ?? document.activeElement?.closest?.('[data-thread]')
    openFileViewer(p, thread ? threadFiles(thread) : undefined)
  }, [])
  return <PreviewCtx.Provider value={show}>{children}</PreviewCtx.Provider>
}
