// The Harness Browser in a window that looks like a browser (LiveView), the same everywhere: "Watch" above a session's
// composer, the "!" of the Office, a topic's / an agent's browser settings. Full screen on a phone. Closing the window
// only hides it: the browser keeps running (it is stopped from its status bar or the session's line). `start`: a
// stopped browser starts when the window opens; `session`: that session's tab is shown; `context`: the topic / agent
// folder it is opened from (share shortcuts).
import * as React from 'react'
import { useT } from '@/i18n'
import { Dialog, DialogContent, DialogDescription, DialogTitle, Skeleton } from '@/components/ui'

const LiveView = React.lazy(() => import('./LiveView').then((m) => ({ default: m.LiveView })))

export function BrowserWindow({ open, onOpenChange, who, start, session, context }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  who?: string
  start?: boolean
  session?: string
  context?: string
}) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="gap-0 overflow-hidden p-0 md:p-0 max-md:inset-0 max-md:max-h-none max-md:rounded-none max-md:pt-(--safe-top) max-md:pb-(--safe-bottom) md:h-[min(88dvh,900px)] md:max-h-none md:max-w-6xl [&>div[aria-hidden]:first-child]:hidden"
        data-testid="browser-window"
      >
        <DialogTitle className="sr-only">{who ? t('browser.topicTitle', { name: who }) : t('browser.name')}</DialogTitle>
        <DialogDescription className="sr-only">{t('browser.dialogDesc')}</DialogDescription>
        <React.Suspense fallback={<Skeleton className="m-4 h-80" />}>
          <LiveView context={context} session={session} who={who} start={start} onMinimize={() => onOpenChange(false)} className="h-full" />
        </React.Suspense>
      </DialogContent>
    </Dialog>
  )
}
