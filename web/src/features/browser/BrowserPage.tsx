// /browser: the Harness Browser (Settings -> Features -> Harness Browser). The second sidebar: the Browser (the person's
// one, on the profile they pick), the Profiles (one per project, `main` = the person's, more added by hand) and the
// Connections (where the pages go out: the server's IP, a phone, a box, a proxy). The page shows the Browser live (also
// an agent's or a session's: ?nav=<id>, ?session=<id> = that session's, its agent's for an agent run), a profile
// (?profile=<id>: its agents' browsers, its sessions' journal, its settings), or a connection (?exit=<id>, ?exit=new to
// add one). ?new=profile opens "Add a profile".
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { Bot, Globe, MessageSquare, Plus } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserNavigator, useBrowserStatus, useSaveBrowserProfile, useSettings } from '@/lib/queries'
import type { BrowserNavigator, BrowserStatus } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Select, Skeleton } from '@/components/ui'
import { PageList } from '@/components/shell/PageList'
import { Callout } from '@/features/common'
import { LiveView } from './LiveView'
import { MyBrowser } from './MyBrowser'
import { ProfilePage } from './ProfilePage'
import { ConnectionPicker } from './ConnectionPicker'
import { AddExit, DirectPanel, ExitPanel } from './Exits'
import { exitLine, exitName, exitTone, navName, orderedProfiles, ownerParts, profileName, testWhere } from './profiles'

/** The navigator a session's link means: its agent's for an agent run, else the session's own. */
function navOfSession(st: BrowserStatus | undefined, session: string): string {
  const own = `session:${session}`
  if (st?.navigators.some((n) => n.id === own)) return own
  const ask = st?.asks.find((a) => a.session === session)
  return ask?.owner.startsWith('agent:') ? `agent:${ask.owner.slice(6)}` : own
}

export default function BrowserPage() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const { data: s } = useSettings()
  const { data: st } = useBrowserStatus(!!s?.browser_feature)
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

  const exit = exitId && exitId !== 'new' && exitId !== 'direct' ? st?.exits.find((e) => e.id === exitId) : undefined
  const n = st?.navigators.find((x) => x.id === navId)
  const navProfile = n?.profile || (session ? st?.summary.turns[session] || st?.asks.find((a) => a.session === session)?.profile : undefined) || (navId === 'me' ? 'main' : undefined)
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="browser-page">
      <PageList id="browser" label={t('nav.browser')} icon={Globe}>
        <SideList navId={exitId || pid ? null : navId} pid={pid} exitId={exitId} onAddProfile={() => setAdding(true)} />
      </PageList>

      {exitId ? (
        <Section title={exitId === 'new' ? t('browser.exit.addTitle') : exitId === 'direct' ? t('browser.exit.direct') : exit?.name || ''}>
          {exitId === 'new' ? <AddExit /> : exitId === 'direct' ? <DirectPanel /> : exit ? <ExitPanel key={exit.id} exit={exit} /> : <Skeleton className="h-40" />}
        </Section>
      ) : pid ? (
        <ProfilePage key={pid} pid={pid} />
      ) : navId === 'me' && !session && params.get('live') !== '1' && st ? (
        <MyBrowser st={st} pid={navProfile || 'main'} onOpen={() => setParams({ live: '1' })} onAgent={(nav) => setParams({ nav })} />
      ) : navProfile ? (
        <Live key={`${navId}:${navProfile}`} nav={n || { id: navId, kind: navId.startsWith('agent:') ? 'agent' : navId.startsWith('session:') ? 'session' : 'person', name: '' }} pid={navProfile} st={st} session={session} onBack={() => setParams({})} />
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

/** A navigator live. The person's Browser: pick its profile and that profile's connection here. An agent's or a
 *  session's: its name, where it is, its profile. */
function Live({ nav, pid, st, session, onBack }: { nav: Pick<BrowserNavigator, 'id' | 'kind' | 'name'> & Partial<BrowserNavigator>; pid: string; st?: BrowserStatus; session?: string; onBack?: () => void }) {
  const t = useT()
  const move = useBrowserNavigator()
  const row = st?.profiles.find((p) => p.id === pid)
  const person = nav.kind === 'person'
  const Icon = nav.kind === 'agent' ? Bot : nav.kind === 'session' ? MessageSquare : Globe
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b px-4 py-1.5">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <h1 className="min-w-0 truncate text-sm font-semibold" data-testid="browser-nav-name">{person ? t('browser.side.browser') : navName(nav, t)}</h1>
        {!person && nav.path && <span className="truncate text-[12px] text-muted-foreground">{ownerParts(nav.path).where || ownerParts(nav.path).name}</span>}
        <span className="flex-1" />
        {person ? (
          <span className="inline-flex items-center gap-1">
            <span className="hidden text-[12px] text-muted-foreground sm:inline">{t('browser.menu.signins')}</span>
            <Select
              className="h-8 w-44 text-[13px]"
              aria-label={t('browser.menu.signins')}
              value={pid}
              onValueChange={(x) => x !== pid && move.mutate({ profile: x })}
              options={orderedProfiles(st?.profiles || [], t).map((p) => ({ value: p.id, label: profileName(p, t) }))}
              data-testid="browser-nav-profile"
            />
          </span>
        ) : (
          <Link to={`/browser?profile=${encodeURIComponent(pid)}`} title={t('browser.nav.signinsTitle')} className="inline-flex h-6 max-w-56 items-center truncate rounded-full border px-2 text-[12px] hover:bg-accent" data-testid="browser-nav-profile">
            {t('browser.nav.signins', { name: profileName(row || { id: pid, name: '' }, t) })}
          </Link>
        )}
        <ConnectionPicker pid={pid} note />
      </div>
      <LiveView profile={pid} nav={nav.id} session={session} who={person ? undefined : navName(nav, t)} start={!!session || person} onMinimize={person ? onBack : undefined} className="min-h-0 flex-1" />
    </div>
  )
}

/** The second sidebar: the Browser, the Profiles (+ Add a profile), the Connections (+ Add a connection). */
function SideList({ navId, pid, exitId, onAddProfile }: { navId: string | null; pid: string | null; exitId: string | null; onAddProfile: () => void }) {
  const t = useT()
  const { data: st } = useBrowserStatus()
  if (!st) return <Skeleton className="m-2 h-40" />
  const waitingProfiles = new Set(st.waiting.map((w) => w.profile))
  const me = st.navigators.find((n) => n.id === 'me')
  const meProfile = st.profiles.find((p) => p.id === me?.profile)
  const blank = !me?.page?.url || me.page.url === 'about:blank'
  const heading = (text: string) => <h3 className="px-2.5 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{text}</h3>
  const add = (label: string, testid: string, active: boolean, onClick?: () => void, to?: string) =>
    to ? (
      <Link to={to} className={cn('mt-0.5 inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] text-primary hover:bg-accent', active && 'bg-accent')} data-testid={testid}>
        <Plus className="size-3.5" /> {label}
      </Link>
    ) : (
      <button type="button" onClick={onClick} className="mt-0.5 inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-primary hover:bg-accent" data-testid={testid}>
        <Plus className="size-3.5" /> {label}
      </button>
    )
  return (
    <div className="grid content-start gap-4 overflow-y-auto p-2" data-testid="browser-side">
      <div className="grid gap-0.5">
        <Row to="/browser" active={navId === 'me'} tone={me?.running && me.awake ? 'bg-success' : 'bg-muted-foreground/50'} title={t('browser.side.browser')} right={me?.running && me.awake ? t('browser.tabsAwake', { count: me.awake }) : ''} testid="browser-side-nav">
          {[profileName(meProfile || { id: me?.profile || 'main', name: '' }, t), blank ? '' : me?.page?.title || me?.page?.url].filter(Boolean).join(' · ')}
        </Row>
        {navId && navId !== 'me' && (
          <Row to={`/browser?nav=${encodeURIComponent(navId)}`} active tone="bg-success" title={navName(st.navigators.find((n) => n.id === navId) || { id: navId, kind: navId.startsWith('agent:') ? 'agent' : 'session', name: '' }, t)}>
            {t(navId.startsWith('agent:') ? 'browser.persistent' : 'browser.temporary')}
          </Row>
        )}
      </div>
      <div className="grid gap-0.5" data-testid="browser-side-profiles">
        {heading(t('browser.profiles'))}
        {orderedProfiles(st.profiles, t).map((p) => {
          const e = st.exits.find((x) => x.id === p.exit)
          const down = e?.state === 'down'
          const tone = down ? 'bg-destructive' : p.state === 'running' ? 'bg-success' : 'bg-muted-foreground/50'
          const line = [
            p.id === 'main' ? t('browser.profile.yours') : p.gone ? t('browser.profile.projectGone') : '',
            p.agents ? (p.agents === 1 ? t('browser.profile.agentsOne') : t('browser.profile.agentsMany', { count: p.agents })) : '',
            exitName(p.exit, st.exits, t),
            down ? t('browser.exit.down') : '',
          ].filter(Boolean)
          return (
            <Row key={p.id} to={`/browser?profile=${encodeURIComponent(p.id)}`} active={pid === p.id} tone={tone} title={profileName(p, t)} right={waitingProfiles.has(p.id) ? t('browser.paused') : ''} testid="browser-side-profile">
              {line.join(' · ')}
            </Row>
          )
        })}
        {add(t('browser.profile.add'), 'browser-side-add-profile', false, onAddProfile)}
      </div>
      <div className="grid gap-0.5" data-testid="browser-side-exits">
        {heading(t('browser.exits'))}
        <Row to="/browser?exit=direct" active={exitId === 'direct'} tone="bg-success" title={t('browser.exit.direct')} testid="browser-side-exit">
          {testWhere(st.direct.test) || t('browser.exit.directLine')}
        </Row>
        {st.exits.map((e) => (
          <Row key={e.id} to={`/browser?exit=${encodeURIComponent(e.id)}`} active={exitId === e.id} tone={exitTone(e)} title={e.name} testid="browser-side-exit">
            {exitLine(e, t)}
          </Row>
        ))}
        {add(t('browser.exit.add'), 'browser-side-add-exit', exitId === 'new', undefined, '/browser?exit=new')}
      </div>
    </div>
  )
}

function Row({ to, active, tone, title, right, testid, children }: { to: string; active: boolean; tone: string; title: string; right?: string; testid?: string; children: React.ReactNode }) {
  return (
    <Link to={to} aria-current={active ? 'page' : undefined} className={cn('grid grid-cols-[0.5rem_minmax(0,1fr)_auto] items-start gap-x-2.5 rounded-md px-2.5 py-1.5 hover:bg-accent', active && 'bg-accent')} data-testid={testid}>
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
          <DialogTitle>{t('browser.profile.add')}</DialogTitle>
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
