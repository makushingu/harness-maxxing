// /browser: the Harness Browser (Settings -> Features -> Harness Browser). The second sidebar lists the profiles (each
// its own Chromium, sign-ins, sites and exit) and the exits (where their pages go out); the page shows the profile
// picked, live (?profile=<id>), its settings (&view=settings), or an exit (?exit=<id>, ?exit=new to add one).
// ?session=<id> shows that session's tab in its profile (the link of a request, "needs you in its browser").
import * as React from 'react'
import { Link, useSearchParams } from 'react-router'
import { Globe, Moon, Plus, Settings2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserProfile, useBrowserStatus, useProfileAction, useSaveBrowserProfile, useSettings } from '@/lib/queries'
import type { BrowserExit, BrowserProfileRow } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuTrigger, Input, Skeleton,
} from '@/components/ui'
import { PageList } from '@/components/shell/PageList'
import { Callout } from '@/features/common'
import { LiveView } from './LiveView'
import { ProfileSettings } from './ProfileSettings'
import { AddExit, DirectPanel, ExitPanel } from './Exits'
import { exitLine, exitName, exitTone, ownerParts, profileName, testWhere } from './profiles'

export default function BrowserPage() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const { data: s } = useSettings()
  const { data: st } = useBrowserStatus(!!s?.browser_feature)
  const [adding, setAdding] = React.useState(false)
  const session = params.get('session') || undefined
  const exitId = params.get('exit')
  const askProfile = session ? st?.summary.turns[session] || st?.asks.find((a) => a.session === session)?.profile : undefined
  const pid = params.get('profile') || askProfile || 'main'
  const settings = params.get('view') === 'settings'

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

  const profile = st?.profiles.find((p) => p.id === pid)
  const exit = exitId && exitId !== 'new' && exitId !== 'direct' ? st?.exits.find((e) => e.id === exitId) : undefined
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
              <DropdownMenuItem onSelect={() => setAdding(true)} data-testid="browser-add-profile">{t('browser.profile.new')}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setParams({ exit: 'new' })}>{t('browser.exit.add')}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        }
      >
        <SideList pid={exitId ? null : pid} exitId={exitId} />
      </PageList>

      {exitId ? (
        <Section title={exitId === 'new' ? t('browser.exit.addTitle') : exitId === 'direct' ? t('browser.exit.direct') : exit?.name || ''}>
          {exitId === 'new' ? <AddExit /> : exitId === 'direct' ? <DirectPanel /> : exit ? <ExitPanel key={exit.id} exit={exit} /> : <Skeleton className="h-40" />}
        </Section>
      ) : settings ? (
        <Section
          title={t('browser.profile.settingsTitle', { name: profileName(profile, t) })}
          actions={
            <Button size="sm" variant="outline" asChild>
              <Link to={`/browser?profile=${encodeURIComponent(pid)}`}>{t('browser.profile.openLive')}</Link>
            </Button>
          }
        >
          <ProfileSettings key={pid} pid={pid} />
        </Section>
      ) : (
        <Live key={`${pid}:${session || ''}`} pid={pid} row={profile} exits={st?.exits} session={session} />
      )}
      <NewProfile open={adding} onOpenChange={setAdding} onDone={(id) => setParams({ profile: id, view: 'settings' })} />
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

/** A profile live: its name, exit, who uses it, its settings, sleep; then the live view. */
function Live({ pid, row, exits, session }: { pid: string; row?: BrowserProfileRow; exits?: BrowserExit[]; session?: string }) {
  const t = useT()
  const { data: v } = useBrowserProfile(pid)
  const action = useProfileAction()
  const e = exits?.find((x) => x.id === row?.exit)
  const where = row?.exit === 'direct' ? t('browser.exit.directLine') : e ? [e.name, testWhere(e.test)].filter(Boolean).join(' · ') : ''
  const users = v?.used_by || []
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b px-4 py-1.5">
        <h1 className="min-w-0 truncate text-sm font-semibold" data-testid="browser-profile-name">{profileName(row || { id: pid, name: '' }, t)}</h1>
        {row && (
          <Badge variant={e?.state === 'down' ? 'destructive' : row.exit === 'direct' ? 'muted' : 'success'} title={t('browser.profile.exit')}>
            <span className={cn('size-1.5 rounded-full', exitTone(e))} /> {t('browser.via', { where })}
          </Badge>
        )}
        {users.length > 0 && (
          <Badge variant="outline" className="max-w-64 truncate font-normal text-muted-foreground">
            {t('browser.usedByShort', { names: users.slice(0, 2).map((u) => ownerParts(u.path).name).join(', ') + (users.length > 2 ? ` +${users.length - 2}` : '') })}
          </Badge>
        )}
        {v?.browser.level === 'live' && <Badge variant="outline" className="font-normal text-sky-600 dark:text-sky-400">{t('browser.levelLive')}</Badge>}
        <span className="flex-1" />
        <Button size="sm" variant="outline" asChild>
          <Link to={`/browser?profile=${encodeURIComponent(pid)}&view=settings`} data-testid="browser-profile-settings-link">
            <Settings2 /> {t('browser.profile.settings')}
          </Link>
        </Button>
        {v?.browser.state === 'running' && (
          <Button size="sm" variant="outline" onClick={() => action.mutate({ profile: pid, action: 'stop' })}>
            <Moon /> {t('browser.profile.sleep')}
          </Button>
        )}
      </div>
      <LiveView profile={pid} session={session} start={!!session} className="min-h-0 flex-1" />
    </div>
  )
}

/** The second sidebar: profiles, then exits (Direct last). */
function SideList({ pid, exitId }: { pid: string | null; exitId: string | null }) {
  const t = useT()
  const { data: st } = useBrowserStatus()
  if (!st) return <Skeleton className="m-2 h-40" />
  const waitingProfiles = new Set(st.waiting.map((w) => w.profile))
  return (
    <div className="grid content-start gap-4 overflow-y-auto p-2" data-testid="browser-side">
      <div className="grid gap-0.5">
        <h3 className="px-2.5 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profiles')}</h3>
        {st.profiles.map((p) => {
          const e = st.exits.find((x) => x.id === p.exit)
          const down = e?.state === 'down'
          const tone = down ? 'bg-destructive' : p.state === 'running' ? 'bg-success' : 'bg-muted-foreground/50'
          const right = waitingProfiles.has(p.id) ? t('browser.paused') : p.state === 'running' ? t('browser.tabsAwake', { count: p.awake }) : ''
          return (
            <Row key={p.id} to={`/browser?profile=${encodeURIComponent(p.id)}`} active={pid === p.id} tone={tone} title={profileName(p, t)} right={right} testid="browser-side-profile">
              {exitName(p.exit, st.exits, t)}
              {e && testWhere(e.test) ? ` · ${testWhere(e.test)}` : ''}
              {down ? ` · ${t('browser.exit.down')}` : p.state !== 'running' ? ` · ${t('browser.asleepShort')}` : ''}
            </Row>
          )
        })}
      </div>
      <div className="grid gap-0.5">
        <h3 className="px-2.5 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.exits')}</h3>
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
