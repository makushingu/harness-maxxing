// The Harness Browser in a window that looks like a browser (LiveView), the same everywhere: "Watch" above a session's
// composer, the "!" of the Office, a topic's / an agent's browser settings. Full screen on a phone. Closing the window
// only hides it: the browser keeps running (it is stopped from its status bar or the Browser page). It shows one
// navigator: the agent's when `context` is an agent folder, else the session's (`session`), unless `nav` says which;
// in the profile that navigator uses (the folder's settings, unless `profile` says which). `start`: a stopped profile
// starts when the window opens.
import * as React from 'react'
import { useT } from '@/i18n'
import { useBrowserNavigator, useBrowserOwner, useBrowserStatus } from '@/lib/queries'
import { Dialog, DialogContent, DialogDescription, DialogTitle, Skeleton } from '@/components/ui'
import { navOf } from './profiles'

const LiveView = React.lazy(() => import('./LiveView').then((m) => ({ default: m.LiveView })))

export function BrowserWindow({ open, onOpenChange, who, start, session, context, profile, nav }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  who?: string
  start?: boolean
  session?: string
  context?: string
  profile?: string
  nav?: string
}) {
  const t = useT()
  const asked = nav || navOf(session, context)
  const person = asked === 'me' && !nav
  const { data: st } = useBrowserStatus(open)
  const known = person ? undefined : st?.navigators.find((n) => n.id === asked)?.profile
  const owner = useBrowserOwner(context || '', open && !profile && !known && !!context)
  const pid = profile || known || owner.data?.profile || (context ? undefined : 'main')
  // a topic's browser, opened by the person: their browser, put on that profile (its tabs follow, asleep)
  const me = st?.navigators.find((n) => n.id === 'me')
  const move = useBrowserNavigator()
  const moved = React.useRef('')
  React.useEffect(() => {
    if (!open || !person || !pid || !me || me.profile === pid || moved.current === pid) return
    moved.current = pid
    move.mutate({ profile: pid })
  }, [open, person, pid, me, move])
  const id = person ? (me && me.profile === pid ? 'me' : undefined) : asked
  const livePid = pid
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="gap-0 overflow-hidden p-0 md:p-0 max-md:inset-0 max-md:max-h-none max-md:rounded-none max-md:pt-(--safe-top) max-md:pb-(--safe-bottom) md:h-[min(92dvh,1200px)] md:max-h-none md:w-[min(96vw,1800px)] md:max-w-none [&>div[aria-hidden]:first-child]:hidden"
        data-testid="browser-window"
      >
        <DialogTitle className="sr-only">{who ? t('browser.topicTitle', { name: who }) : t('browser.name')}</DialogTitle>
        <DialogDescription className="sr-only">{t('browser.dialogDesc')}</DialogDescription>
        <React.Suspense fallback={<Skeleton className="m-4 h-80" />}>
          {livePid && id ? (
            <LiveView profile={livePid} nav={id} session={session} who={who} start={start} onMinimize={() => onOpenChange(false)} className="h-full" />
          ) : (
            <Skeleton className="m-4 h-80" />
          )}
        </React.Suspense>
      </DialogContent>
    </Dialog>
  )
}
