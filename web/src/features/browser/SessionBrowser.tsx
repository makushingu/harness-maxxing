// The Harness Browser in a session: a line above the composer while this session uses it ("Claude is using the
// browser") or while it has tabs open in its profile (Watch, x to hide the line); while Claude waits for the user in it
// (its request, Open, Skip); and while its turn stopped because the profile's exit is down (Go on when it is back,
// Retry now, Open the exit). Watch opens the browser window (BrowserWindow) on this session's navigator (the agent's in
// an agent folder), as does a new request or ?browser=1 (the notification's link).
import * as React from 'react'
import { Link } from 'react-router'
import { CloudOff, Globe, Hand, SkipForward, X } from 'lucide-react'
import { useT } from '@/i18n'
import { useAnswerAsk, useBrowserOwner, useBrowserProfile, useBrowserStatus, useExitWait, useSessionBrowserAsks, useSettings } from '@/lib/queries'
import type { Session } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui'
import { openBrowserOf, useBrowserWanted } from './open'
import { BrowserWindow } from './BrowserWindow'
import { exitName, navOf } from './profiles'

/** A topic or an agent folder: the folders that may use the browser. */
const BROWSER_PATH = /^projects\/[^/]+\/topics\/[^/]+(\/agents\/[^/]+)?$/

/** Requests already shown once: a new one opens the window by itself, never again after the user closed it. */
const opened = new Set<string>()
/** Sessions whose line the user hid (until Claude uses the browser again). */
const hidden = new Set<string>()

/** Above the composer: nothing unless the browser feature is on and the session is in a topic or an agent. */
export function SessionBrowserBar({ session }: { session: Session | undefined }) {
  const { data: s } = useSettings()
  if (!s?.browser_feature || !session || !BROWSER_PATH.test(session.path || '')) return null
  return <Bar session={session} />
}

function Bar({ session }: { session: Session }) {
  const t = useT()
  const { data: st } = useBrowserStatus()
  const { data: asks } = useSessionBrowserAsks(session.id, !!session.browser_asks)
  const answer = useAnswerAsk()
  const open = useBrowserWanted(session.id)
  const [, redraw] = React.useReducer((n: number) => n + 1, 0)
  const { data: o } = useBrowserOwner(session.path || '')
  const nav = navOf(session.id, session.path)
  const turnProfile = st?.summary.turns[session.id]
  const pid = turnProfile || st?.navigators.find((n) => n.id === nav)?.profile || o?.profile || 'main'
  const { data: v } = useBrowserProfile(pid, !!st?.summary.running.includes(pid))
  const b = v?.browser
  const running = b?.state === 'running'
  const waiting = asks || []
  const using = !!turnProfile
  const tabs = running ? (b?.tabs || []).filter((x) => !x.asleep && x.nav === nav) : []
  const tab = [...tabs].sort((x, y) => y.used - x.used)[0]
  const down = session.browser_exit
  if (using) hidden.delete(session.id)

  // A new request opens the window (once: closing it is respected).
  const fresh = waiting.find((a) => !opened.has(a.id))
  React.useEffect(() => {
    if (!fresh) return
    opened.add(fresh.id)
    openBrowserOf(session.id)
  }, [fresh, session.id])

  const line = running && (using || tabs.length > 0) && !hidden.has(session.id)
  if (!line && !waiting.length && !open && !down) return null
  return (
    <div className="mx-auto grid w-full max-w-(--mx-read,860px) shrink-0 gap-1.5 px-3 pb-2" data-testid="session-browser">
      {waiting.map((a) => (
        <div key={a.id} className="mx-rise flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-warning/50 bg-warning/8 px-2.5 py-1.5 text-[13px]" data-testid="session-browser-ask">
          <Hand className="size-3.5 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">
            <span className="font-medium">{t('browser.ask.title')}</span> {a.reason}
          </span>
          <Button size="sm" className="h-6 px-2.5 text-xs" onClick={() => openBrowserOf(session.id)}>
            {t('browser.openWindow')}
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => answer.mutate({ id: a.id, action: 'skip' })}>
            <SkipForward className="size-3.5" /> {t('browser.ask.skip')}
          </Button>
        </div>
      ))}
      {down && <ExitDown session={session.id} exitId={down.exit} name={exitName(down.exit, st?.exits, t)} resume={down.resume} />}
      {line && !waiting.length && (
        <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-card py-1 pr-1 pl-2.5 text-[13px]">
          <Globe className={cn('size-3.5 shrink-0 text-primary', using && 'animate-pulse')} />
          <span className="min-w-0 flex-1 truncate">
            <span className="font-medium">{using ? t('browser.bar.on') : t('browser.bar.tabs', { count: tabs.length })}</span>{' '}
            <span className="font-mono text-[12px] text-muted-foreground">{tab && tab.url !== 'about:blank' ? tab.url : ''}</span>
          </span>
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => openBrowserOf(session.id)} data-testid="session-browser-watch">
            {t('browser.bar.watch')}
          </Button>
          <Button size="icon-sm" variant="ghost" className="size-6" onClick={() => (hidden.add(session.id), redraw())} title={t('browser.bar.hide')} aria-label={t('browser.bar.hide')} data-testid="session-browser-close">
            <X className="size-3.5" />
          </Button>
        </div>
      )}
      <BrowserWindow context={session.path} profile={pid} nav={nav} session={session.id} open={open} onOpenChange={(v) => openBrowserOf(v ? session.id : null)} start />
    </div>
  )
}

/** The turn stopped: its profile's exit is down. Never goes out another way by itself. */
function ExitDown({ session, exitId, name, resume }: { session: string; exitId: string; name: string; resume: boolean }) {
  const t = useT()
  const act = useExitWait()
  return (
    <div className="mx-rise flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/6 px-2.5 py-1.5 text-[13px]" data-testid="session-browser-exit">
      <CloudOff className="size-3.5 shrink-0 text-destructive" />
      <span className="min-w-0 flex-1">
        <span className="font-medium">{t('browser.down.title', { name })}</span> {t(resume ? 'browser.down.resumeOn' : 'browser.down.desc')}
      </span>
      {!resume && (
        <Button size="sm" className="h-6 px-2.5 text-xs" loading={act.isPending && act.variables?.action === 'resume'} onClick={() => act.mutate({ session, action: 'resume' })} data-testid="session-browser-exit-resume">
          {t('browser.down.resume')}
        </Button>
      )}
      <Button size="sm" variant="outline" className="h-6 px-2.5 text-xs" loading={act.isPending && act.variables?.action === 'retry'} onClick={() => act.mutate({ session, action: 'retry' })}>
        {t('browser.down.retry')}
      </Button>
      <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" asChild>
        <Link to={`/settings/browser?exit=${encodeURIComponent(exitId)}`}>{t('browser.down.open')}</Link>
      </Button>
      <Button size="icon-sm" variant="ghost" className="size-6" onClick={() => act.mutate({ session, action: 'dismiss' })} title={t('browser.bar.hide')} aria-label={t('browser.bar.hide')}>
        <X className="size-3.5" />
      </Button>
    </div>
  )
}
