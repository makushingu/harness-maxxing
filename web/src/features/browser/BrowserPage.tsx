// /browser: the Harness Browser (Settings -> Features -> Harness Browser). The second sidebar lists the navigators
// (windows of tabs: the person's, each agent's, the sessions' lately), the profiles (sign-ins, sites and exit: one
// Chromium each, shared by the navigators on it) and the exits (where their pages go out). The page shows a navigator
// live (?nav=<id>, "me" by default), a profile's settings (?profile=<id>), or an exit (?exit=<id>, ?exit=new to add
// one). ?session=<id> shows the navigator of that session (its agent's for an agent run: the link of a request).
// ?new=profile opens "New profile".
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { Bot, Globe, MessageSquare, MoreHorizontal, Pencil, Plus, User, X } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserNavigator, useBrowserProfile, useBrowserStatus, useSaveBrowserProfile, useSettings } from '@/lib/queries'
import type { BrowserNavigator, BrowserStatus } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  Badge, Button, confirm, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuTrigger, Input, Skeleton,
} from '@/components/ui'
import { PageList } from '@/components/shell/PageList'
import { Callout } from '@/features/common'
import { LiveView } from './LiveView'
import { ProfileSettings } from './ProfileSettings'
import { AddExit, DirectPanel, ExitPanel } from './Exits'
import { exitLine, exitName, exitTone, navName, ownerParts, profileName, testWhere } from './profiles'

/** The navigator a session's link means: its agent's for an agent run, else the session's own. */
function navOfSession(st: BrowserStatus | undefined, session: string): string {
  const own = `session:${session}`
  if (st?.navigators.some((n) => n.id === own)) return own
  const ask = st?.asks.find((a) => a.session === session)
  return ask?.owner.startsWith('agent:') ? `agent:${ask.owner.slice(6)}` : own
}

export default function BrowserPage() {
  const t = useT()
  const go = useNavigate()
  const [params, setParams] = useSearchParams()
  const { data: s } = useSettings()
  const { data: st } = useBrowserStatus(!!s?.browser_feature)
  const make = useBrowserNavigator()
  const [adding, setAdding] = React.useState(params.get('new') === 'profile')
  const session = params.get('session') || undefined
  const exitId = params.get('exit')
  const pid = params.get('profile')
  const navId = params.get('nav') || (session ? navOfSession(st, session) : 'me')

  if (s && !s.browser_feature)
    return (
      <div className="p-4">
        <Callout tone="info">
          {t('browser.featureOff')}{' '}
          <Link to="/settings/features" className="text-primary underline">
            {t('browser.openFeatures')}
          </Link>
        </Callout>
      </div>
    )

  const newNav = () => make.mutate({}, { onSuccess: (n) => n && typeof n === 'object' && 'id' in n && go(`/browser?nav=${encodeURIComponent(String(n.id))}`) })
  const profile = pid ? st?.profiles.find((p) => p.id === pid) : undefined
  const exit = exitId && exitId !== 'new' && exitId !== 'direct' ? st?.exits.find((e) => e.id === exitId) : undefined
  const n = st?.navigators.find((x) => x.id === navId)
  const navProfile = n?.profile || (session ? st?.summary.turns[session] || st?.asks.find((a) => a.session === session)?.profile : undefined) || (navId === 'me' ? 'main' : undefined)
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="browser-page">
      <PageList
        id="browser"
        label={t('nav.browser')}
        icon={Globe}
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('browser.addMenu')} data-testid="browser-add">
                <Plus />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={newNav} data-testid="browser-add-nav">{t('browser.nav.new')}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setAdding(true)} data-testid="browser-add-profile">{t('browser.profile.new')}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setParams({ exit: 'new' })}>{t('browser.exit.add')}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        }
      >
        <SideList navId={exitId || pid ? null : navId} pid={pid} exitId={exitId} onNewNav={newNav} />
      </PageList>

      {exitId ? (
        <Section title={exitId === 'new' ? t('browser.exit.addTitle') : exitId === 'direct' ? t('browser.exit.direct') : exit?.name || ''}>
          {exitId === 'new' ? <AddExit /> : exitId === 'direct' ? <DirectPanel /> : exit ? <ExitPanel key={exit.id} exit={exit} /> : <Skeleton className="h-40" />}
        </Section>
      ) : pid ? (
        <Section title={t('browser.profile.settingsTitle', { name: profileName(profile || { id: pid, name: '' }, t) })}>
          <ProfileSettings key={pid} pid={pid} />
        </Section>
      ) : navProfile ? (
        <Live key={`${navId}:${navProfile}`} nav={n || { id: navId, kind: navId.startsWith('agent:') ? 'agent' : navId.startsWith('session:') ? 'session' : 'person', name: '' }} pid={navProfile} st={st} session={session} />
      ) : (
        <Skeleton className="m-4 h-80" />
      )}
      <NewProfile open={adding} onOpenChange={setAdding} onDone={(id) => setParams({ profile: id })} />
    </div>
  )
}

function Section({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-12 shrink-0 items-center gap-2 border-b px-4">
        <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h1>
        {actions}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </div>
  )
}

/** A navigator live: its name, the sign-ins (profile) and exit it uses; rename / close the person's; the live view. */
function Live({ nav, pid, st, session }: { nav: Pick<BrowserNavigator, 'id' | 'kind' | 'name'> & Partial<BrowserNavigator>; pid: string; st?: BrowserStatus; session?: string }) {
  const t = useT()
  const go = useNavigate()
  const { data: v } = useBrowserProfile(pid)
  const change = useBrowserNavigator()
  const [renaming, setRenaming] = React.useState(false)
  const row = st?.profiles.find((p) => p.id === pid)
  const e = st?.exits.find((x) => x.id === row?.exit)
  const where = row?.exit === 'direct' ? t('browser.exit.directLine') : e ? [e.name, testWhere(e.test)].filter(Boolean).join(' · ') : ''
  const close = async () => {
    if (!(await confirm({ title: t('browser.nav.closeTitle', { name: navName(nav, t) }), description: t('browser.nav.closeDesc'), destructive: true }))) return
    change.mutate({ id: nav.id, remove: true }, { onSuccess: () => go('/browser') })
  }
  const Icon = nav.kind === 'agent' ? Bot : nav.kind === 'session' ? MessageSquare : User
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b px-4 py-1.5">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <h1 className="min-w-0 truncate text-sm font-semibold" data-testid="browser-nav-name">{navName(nav, t)}</h1>
        {nav.kind !== 'person' && nav.path && <span className="truncate text-[12px] text-muted-foreground">{ownerParts(nav.path).where || ownerParts(nav.path).name}</span>}
        <Link to={`/browser?profile=${encodeURIComponent(pid)}`} title={t('browser.nav.signinsTitle')} className="inline-flex h-5 max-w-56 items-center truncate rounded-full border px-2 text-[11px] hover:bg-accent/50" data-testid="browser-nav-profile">
          {t('browser.nav.signins', { name: profileName(row || { id: pid, name: '' }, t) })}
        </Link>
        {row && (
          <Badge variant={e?.state === 'down' ? 'destructive' : row.exit === 'direct' ? 'muted' : 'success'} title={t('browser.profile.exit')}>
            <span className={cn('size-1.5 rounded-full', exitTone(e))} /> {t('browser.via', { where })}
          </Badge>
        )}
        {v?.browser.level === 'live' && <Badge variant="outline" className="font-normal text-sky-600 dark:text-sky-400">{t('browser.levelLive')}</Badge>}
        <span className="flex-1" />
        {nav.kind === 'person' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('browser.nav.more')} data-testid="browser-nav-more">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setRenaming(true)}>
                <Pencil /> {t('browser.nav.rename')}
              </DropdownMenuItem>
              {nav.id !== 'me' && (
                <DropdownMenuItem destructive onSelect={close} data-testid="browser-nav-close">
                  <X /> {t('browser.nav.close')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <LiveView profile={pid} nav={nav.id} session={session} start={!!session} className="min-h-0 flex-1" />
      <RenameNav nav={nav} open={renaming} onOpenChange={setRenaming} />
    </div>
  )
}

function RenameNav({ nav, open, onOpenChange }: { nav: Pick<BrowserNavigator, 'id' | 'kind' | 'name'>; open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT()
  const change = useBrowserNavigator()
  const [name, setName] = React.useState(nav.name)
  React.useEffect(() => {
    if (open) setName(nav.name)
  }, [open, nav.name])
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('browser.nav.rename')}</DialogTitle>
          <DialogDescription>{t('browser.nav.renameDesc')}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            change.mutate({ id: nav.id, name: name.trim() }, { onSuccess: () => onOpenChange(false) })
          }}
        >
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={navName({ ...nav, name: '' }, t)} maxLength={80} />
          <DialogFooter>
            <Button type="submit" loading={change.isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The second sidebar: the person's navigators, the agents', the sessions', then profiles and exits (Direct last). */
function SideList({ navId, pid, exitId, onNewNav }: { navId: string | null; pid: string | null; exitId: string | null; onNewNav: () => void }) {
  const t = useT()
  const { data: st } = useBrowserStatus()
  if (!st) return <Skeleton className="m-2 h-40" />
  const waitingProfiles = new Set(st.waiting.map((w) => w.profile))
  const profileOf = (id: string | null) => st.profiles.find((p) => p.id === id)
  const navRow = (n: BrowserNavigator) => {
    const p = profileOf(n.profile)
    const tone = !n.profile ? 'bg-destructive' : n.running && n.awake ? 'bg-success' : 'bg-muted-foreground/50'
    const blank = !n.page?.url || n.page.url === 'about:blank'
    const what = blank ? '' : n.page?.title || n.page?.url || ''
    return (
      <Row key={n.id} to={`/browser?nav=${encodeURIComponent(n.id)}`} active={navId === n.id} tone={tone} title={navName(n, t)} right={n.turns ? t('browser.nav.acting') : n.running && n.awake ? t('browser.tabsAwake', { count: n.awake }) : ''} testid="browser-side-nav">
        {[p ? profileName(p, t) : t('browser.nav.noProfile'), what || (n.running && n.awake ? '' : t('browser.asleepShort'))].filter(Boolean).join(' · ')}
      </Row>
    )
  }
  const mine = st.navigators.filter((n) => n.kind === 'person')
  const agents = st.navigators.filter((n) => n.kind === 'agent')
  const sessions = st.navigators.filter((n) => n.kind === 'session')
  const heading = (text: string) => <h3 className="px-2.5 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{text}</h3>
  return (
    <div className="grid content-start gap-4 overflow-y-auto p-2" data-testid="browser-side">
      <div className="grid gap-0.5" data-testid="browser-side-mine">
        {heading(t('browser.navs.yours'))}
        {mine.map(navRow)}
        {mine.length < 8 && (
          <button type="button" onClick={onNewNav} className="mt-0.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-primary hover:bg-accent/50" data-testid="browser-side-new-nav">
            + {t('browser.nav.new')}
          </button>
        )}
      </div>
      {agents.length > 0 && (
        <div className="grid gap-0.5" data-testid="browser-side-agents">
          {heading(t('browser.navs.agents'))}
          {agents.map(navRow)}
        </div>
      )}
      {sessions.length > 0 && (
        <div className="grid gap-0.5" data-testid="browser-side-sessions">
          {heading(t('browser.navs.sessions'))}
          {sessions.map(navRow)}
        </div>
      )}
      <div className="grid gap-0.5">
        {heading(t('browser.profiles'))}
        {st.profiles.map((p) => {
          const e = st.exits.find((x) => x.id === p.exit)
          const down = e?.state === 'down'
          const tone = down ? 'bg-destructive' : p.state === 'running' ? 'bg-success' : 'bg-muted-foreground/50'
          return (
            <Row key={p.id} to={`/browser?profile=${encodeURIComponent(p.id)}`} active={pid === p.id} tone={tone} title={p.agent ? t('browser.profile.agentOwn', { name: ownerParts(p.agent).name }) : profileName(p, t)} right={waitingProfiles.has(p.id) ? t('browser.paused') : ''} testid="browser-side-profile">
              {exitName(p.exit, st.exits, t)}
              {e && testWhere(e.test) ? ` · ${testWhere(e.test)}` : ''}
              {down ? ` · ${t('browser.exit.down')}` : ''}
            </Row>
          )
        })}
      </div>
      <div className="grid gap-0.5">
        {heading(t('browser.exits'))}
        {st.exits.map((e) => (
          <Row key={e.id} to={`/browser?exit=${encodeURIComponent(e.id)}`} active={exitId === e.id} tone={exitTone(e)} title={e.name} testid="browser-side-exit">
            {exitLine(e, t)}
          </Row>
        ))}
        <Row to="/browser?exit=direct" active={exitId === 'direct'} tone="bg-success" title={t('browser.exit.direct')}>
          {t('browser.exit.directLine')}
        </Row>
        <Link to="/browser?exit=new" className={cn('mt-1 rounded-md px-2.5 py-1.5 text-[13px] text-primary hover:bg-accent/50', exitId === 'new' && 'bg-accent')} data-testid="browser-side-add-exit">
          + {t('browser.exit.add')}
        </Link>
      </div>
    </div>
  )
}

function Row({ to, active, tone, title, right, testid, children }: { to: string; active: boolean; tone: string; title: string; right?: string; testid?: string; children: React.ReactNode }) {
  return (
    <Link to={to} aria-current={active ? 'page' : undefined} className={cn('grid grid-cols-[0.5rem_minmax(0,1fr)_auto] items-start gap-x-2.5 rounded-md px-2.5 py-1.5 hover:bg-accent/50', active && 'bg-accent')} data-testid={testid}>
      <span className={cn('mt-1.5 size-2 rounded-full', tone)} />
      <span className="grid min-w-0">
        <span className="truncate text-[13px] font-medium">{title}</span>
        <span className="truncate text-[12px] text-muted-foreground">{children}</span>
      </span>
      {right ? <span className="pt-0.5 text-[11px] text-muted-foreground">{right}</span> : <span />}
    </Link>
  )
}

function NewProfile({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (v: boolean) => void; onDone: (id: string) => void }) {
  const t = useT()
  const save = useSaveBrowserProfile()
  const [name, setName] = React.useState('')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('browser.profile.new')}</DialogTitle>
          <DialogDescription>{t('browser.profile.newDesc')}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            save.mutate({ name: name.trim() }, {
              onSuccess: (p) => {
                setName('')
                onOpenChange(false)
                if ('id' in p) onDone(p.id)
              },
            })
          }}
        >
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('browser.profile.namePh')} maxLength={40} data-testid="browser-new-profile-name" />
          <DialogFooter>
            <Button type="submit" disabled={!name.trim()} loading={save.isPending}>
              {t('browser.profile.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
