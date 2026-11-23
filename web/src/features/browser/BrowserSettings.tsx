// Settings -> Browser (/settings/browser): the Harness Browser. Its switch and what this server lacks (Set up), then
// My browser (its picture, profile and connection; "Open" = its window), the Profiles (one per project, `main` =
// "General" = the person's and the projects general and system, more added by hand), the Connections (where the
// pages go out: the server's IP, a phone, a box, a proxy) and the settings shared by every profile.
// ?profile=<id> = a profile's page (its agents' browsers, its sessions' journal, its settings), ?exit=<id> a
// connection (?exit=new: add one), ?new=profile "Add a profile". The live view is always a window over this page:
// ?live=1 = my browser's, ?nav=<id> another navigator's, ?session=<id> a session's (its agent's for an agent run).
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { ArrowLeft, Plus } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserStatus, useSaveBrowserProfile, useSettings } from '@/lib/queries'
import type { BrowserStatus } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Skeleton } from '@/components/ui'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'
import { BrowserFeature, BrowserSettingsForm } from './BrowserFeature'
import { BrowserWindow } from './BrowserWindow'
import { MyBrowser } from './MyBrowser'
import { ProfilePage } from './ProfilePage'
import { AddExit, DirectPanel, ExitPanel } from './Exits'
import { openMyBrowser, useMyBrowserOpen } from './open'
import { exitLine, exitName, exitTone, navName, orderedProfiles, profileName, testWhere } from './profiles'

const BROWSER_SETTINGS = '/settings/browser'

/** The navigator a session's link means: its agent's for an agent run, else the session's own. */
function navOfSession(st: BrowserStatus | undefined, session: string): string {
  const own = `session:${session}`
  if (st?.navigators.some((n) => n.id === own)) return own
  const ask = st?.asks.find((a) => a.session === session)
  return ask?.owner.startsWith('agent:') ? `agent:${ask.owner.slice(6)}` : own
}

export function BrowserSettingsSection() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const { data: s } = useSettings()
  const on = !!s?.browser_feature
  const { data: st } = useBrowserStatus(on)
  const [adding, setAdding] = React.useState(params.get('new') === 'profile')
  const exitId = params.get('exit')
  const pid = params.get('profile')
  const session = params.get('session') || undefined
  const navId = params.get('nav') || (session ? navOfSession(st, session) : null)
  const drop = (...keys: string[]) =>
    setParams((p) => {
      const next = new URLSearchParams(p)
      keys.forEach((k) => next.delete(k))
      return next
    }, { replace: true })

  // ?live=1: my browser's window (shared with the rest of the app); the address loses it when the window closes
  const live = params.get('live') === '1'
  const mineOpen = useMyBrowserOpen()
  React.useEffect(() => {
    if (live && on) openMyBrowser()
  }, [live, on])
  const wasOpen = React.useRef(false)
  React.useEffect(() => {
    if (wasOpen.current && !mineOpen && live) drop('live')
    wasOpen.current = mineOpen
  })

  const back = (
    <Link to={BROWSER_SETTINGS} className="inline-flex items-center gap-1.5 justify-self-start text-[13px] text-muted-foreground hover:text-foreground pointer-coarse:min-h-10" data-testid="browser-settings-back">
      <ArrowLeft className="size-4" /> {t('nav.browser')}
    </Link>
  )
  const exit = exitId && exitId !== 'new' && exitId !== 'direct' ? st?.exits.find((e) => e.id === exitId) : undefined
  const other = navId && navId !== 'me' ? st?.navigators.find((n) => n.id === navId) : undefined
  const otherProfile = other?.profile || (session ? st?.summary.turns[session] || st?.asks.find((a) => a.session === session)?.profile : undefined)

  let body: React.ReactNode
  if (!on || !st) body = <BrowserFeature />
  else if (exitId)
    body = (
      <SectionStack>
        {back}
        <SettingsCard title={exitId === 'new' ? t('browser.exit.addTitle') : exitId === 'direct' ? t('browser.exit.direct') : exit?.name || ''}>
          {exitId === 'new' ? <AddExit /> : exitId === 'direct' ? <DirectPanel /> : exit ? <ExitPanel key={exit.id} exit={exit} /> : <Skeleton className="h-40" />}
        </SettingsCard>
      </SectionStack>
    )
  else if (pid)
    body = (
      <SectionStack>
        {back}
        <SettingsCard>
          <ProfilePage key={pid} pid={pid} />
        </SettingsCard>
      </SectionStack>
    )
  else
    body = (
      <SectionStack>
        <BrowserFeature />
        <SettingsCard title={t('browser.side.browser')}>
          <MyBrowser st={st} pid={st.navigators.find((n) => n.id === 'me')?.profile || 'main'} onOpen={() => openMyBrowser()} onAgent={(nav) => setParams({ nav })} />
        </SettingsCard>
        <SettingsCard title={t('browser.profiles')} description={t('browser.profilesDesc')}>
          <Profiles st={st} onAdd={() => setAdding(true)} />
        </SettingsCard>
        <SettingsCard title={t('browser.exits')} description={t('browser.exitsDesc')}>
          <Exits st={st} />
        </SettingsCard>
        <SettingsCard title={t('browser.behaviour')}>
          <BrowserSettingsForm />
        </SettingsCard>
      </SectionStack>
    )

  return (
    <div data-testid="browser-page">
      {body}
      {on && navId && navId !== 'me' && (
        <BrowserWindow
          open
          onOpenChange={(o) => !o && drop('nav', 'session')}
          nav={navId}
          profile={otherProfile}
          session={session}
          who={navName(other || { id: navId, kind: navId.startsWith('agent:') ? 'agent' : 'session', name: '' }, t)}
          start={!!session}
        />
      )}
      <NewProfile open={adding} onOpenChange={(o) => (setAdding(o), !o && params.get('new') && drop('new'))} onDone={(id) => setParams({ profile: id })} />
    </div>
  )
}

/** The profiles: General first, then one per project, then the ones added by hand. */
function Profiles({ st, onAdd }: { st: BrowserStatus; onAdd: () => void }) {
  const t = useT()
  const waiting = new Set(st.waiting.map((w) => w.profile))
  return (
    <div className="grid gap-0.5" data-testid="browser-side-profiles">
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
          <Row key={p.id} to={`${BROWSER_SETTINGS}?profile=${encodeURIComponent(p.id)}`} tone={tone} title={profileName(p, t)} right={waiting.has(p.id) ? t('browser.paused') : ''} testid="browser-side-profile">
            {line.join(' · ')}
          </Row>
        )
      })}
      <AddRow label={t('browser.profile.add')} testid="browser-side-add-profile" onClick={onAdd} />
    </div>
  )
}

/** The connections: the server's address first, then the ones added. */
function Exits({ st }: { st: BrowserStatus }) {
  const t = useT()
  return (
    <div className="grid gap-0.5" data-testid="browser-side-exits">
      <Row to={`${BROWSER_SETTINGS}?exit=direct`} tone="bg-success" title={t('browser.exit.direct')} testid="browser-side-exit">
        {testWhere(st.direct.test) || t('browser.exit.directLine')}
      </Row>
      {st.exits.map((e) => (
        <Row key={e.id} to={`${BROWSER_SETTINGS}?exit=${encodeURIComponent(e.id)}`} tone={exitTone(e)} title={e.name} testid="browser-side-exit">
          {exitLine(e, t)}
        </Row>
      ))}
      <AddRow label={t('browser.exit.add')} testid="browser-side-add-exit" to={`${BROWSER_SETTINGS}?exit=new`} />
    </div>
  )
}

function Row({ to, tone, title, right, testid, children }: { to: string; tone: string; title: string; right?: string; testid?: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="grid grid-cols-[0.5rem_minmax(0,1fr)_auto] items-start gap-x-2.5 rounded-md px-2.5 py-2 hover:bg-accent" data-testid={testid}>
      <span className={cn('mt-1.5 size-2 rounded-full', tone)} />
      <span className="grid min-w-0">
        <span className="truncate text-[13px] font-medium">{title}</span>
        <span className="truncate text-[12px] text-muted-foreground">{children}</span>
      </span>
      {right ? <span className="pt-0.5 text-[11px] text-muted-foreground">{right}</span> : <span />}
    </Link>
  )
}

function AddRow({ label, testid, onClick, to }: { label: string; testid: string; onClick?: () => void; to?: string }) {
  const cls = 'mt-0.5 inline-flex items-center gap-1.5 justify-self-start rounded-md px-2.5 py-1.5 text-[13px] text-primary hover:bg-accent pointer-coarse:min-h-10'
  return to ? (
    <Link to={to} className={cls} data-testid={testid}>
      <Plus className="size-3.5" /> {label}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls} data-testid={testid}>
      <Plus className="size-3.5" /> {label}
    </button>
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
