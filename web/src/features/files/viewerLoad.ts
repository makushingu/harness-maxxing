// The file viewer's chunk (Viewer.tsx) with its words: loaded on the first file opened, or a little before - once
// the shell is idle (lib/prefetchIdle.ts) and when the pointer reaches a file of a conversation (AppShell).
import { withGroups } from '@/i18n'

let loading: Promise<typeof import('./Viewer')> | null = null
export function loadFileViewer() {
  return (loading ??= withGroups(['files'], () => import('./Viewer'))().catch((e) => {
    loading = null // offline: the next opening tries again
    throw e
  }))
}
export const warmFileViewer = () => void loadFileViewer().catch(() => undefined)
