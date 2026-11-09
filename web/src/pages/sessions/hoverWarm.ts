// A session row the mouse rests on (tree of the page or of the sidebar) starts loading its thread, so the click
// opens it with its messages already there - the column's entrance never reveals a spinner. A short dwell keeps a
// pointer sweeping across the tree from firing a request per row; a session already loaded is skipped
// (prefetchTail asks the log cache).
import { canPrefetch } from '@/lib/prefetchIdle'
import { prefetchTail } from '@/lib/queries'

const DWELL_MS = 90
let timer = 0

export function warmProps(id: string) {
  const start = (e: { pointerType?: string }) => {
    if (e.pointerType && e.pointerType !== 'mouse') return
    window.clearTimeout(timer)
    timer = window.setTimeout(() => canPrefetch() && prefetchTail(id), DWELL_MS)
  }
  return {
    onPointerEnter: start,
    onPointerLeave: () => window.clearTimeout(timer),
    onFocus: () => start({}),
  }
}
