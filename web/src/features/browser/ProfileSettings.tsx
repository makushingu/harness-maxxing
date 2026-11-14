// A profile of the Harness Browser (Browser page -> a profile -> Profile settings): its name, its exit, its sites, what
// happens when its exit goes down; who uses it (chosen there or inherited); its memory; forget its sign-ins, delete it.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { Eraser, Moon, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserProfile, useBrowserStatus, useProfileAction, useSaveBrowserProfile } from '@/lib/queries'
import type { BrowserProfile } from '@/lib/types'
import { fmtBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge, Button, confirm, Input, Label, Select, Skeleton } from '@/components/ui'
import { ListEditor } from '@/features/agents/AgentSettings'
import { exitLine, exitName, exitTone, ownerParts, profileName } from './profiles'

export function ProfileSettings({ pid }: { pid: string }) {
  const t = useT()
  const nav = useNavigate()
  const { data: v } = useBrowserProfile(pid)
  const { data: st } = useBrowserStatus()
  const save = useSaveBrowserProfile()
  const action = useProfileAction()
  const [name, setName] = React.useState('')
  const [err, setErr] = React.useState<string | null>(null)
  React.useEffect(() => setName(v?.profile.name || ''), [v?.profile.name])
  if (!v) return <Skeleton className="h-64" />
  const p = v.profile
  const set = (patch: Partial<BrowserProfile>, done?: () => void) =>
    save.mutate({ id: p.id, ...patch }, { onSuccess: () => (setErr(null), done?.()), onError: (e) => setErr(e instanceof Error ? e.message : String(e)) })
  const exits = st?.exits || []
  const exitOptions = [
    { value: 'direct', label: <ExitOption tone="bg-success" name={t('browser.exit.direct')} line={t('browser.exit.directLine')} /> },
    ...exits.map((e) => ({ value: e.id, label: <ExitOption tone={exitTone(e)} name={e.name} line={exitLine(e, t)} /> })),
    { value: '__new', label: <span className="text-primary">{t('browser.exit.add')}</span> },
  ]
  const b = v.browser
  const mine = st?.navigators.find((n) => n.kind === 'person' && n.profile === p.id)
  const forget = async () => {
    if (!(await confirm({ title: t('browser.forgetTitle'), description: t('browser.forgetConfirm'), destructive: true }))) return
    action.mutate({ profile: p.id, action: 'forget' })
  }
  const remove = async () => {
    if (!(await confirm({ title: t('browser.profile.deleteTitle', { name: profileName(p, t) }), description: t('browser.profile.deleteDesc'), destructive: true }))) return
    save.mutate({ id: p.id, remove: true }, { onSuccess: () => nav('/browser') })
  }
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]" data-testid="browser-profile-settings">
      <div className="grid content-start gap-5">
        <div className="grid gap-1.5">
          <Label htmlFor="pr-name">{t('browser.profile.name')}</Label>
          <Input
            id="pr-name"
            value={name}
            placeholder={p.id === 'main' ? t('browser.mainProfile') : ''}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name !== p.name && (name.trim() || p.id === 'main') && set({ name: name.trim() })}
            maxLength={40}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="pr-exit">{t('browser.profile.exit')}</Label>
          <Select id="pr-exit" value={p.exit} onValueChange={(x) => (x === '__new' ? nav('/browser?exit=new') : set({ exit: x }))} options={exitOptions} />
          <p className="text-[12px] text-muted-foreground">{t('browser.profile.exitHint')}</p>
        </div>
        <div className="grid gap-2">
          <Label>{t('browser.sites')}</Label>
          <Choice on={p.web === 'list'} onPick={() => set({ web: 'list' })} title={t('browser.web.list')} testid="browser-web-list">
            {p.web === 'list' && (
              <ListEditor
                value={p.sites}
                onChange={(sites, saved) => set({ sites }, saved)}
                placeholder={t('browser.sitesPlaceholder')}
                empty={t('browser.sitesEmpty')}
                error={err}
                testid="browser-sites"
              />
            )}
          </Choice>
          <Choice on={p.web === 'public'} onPick={() => set({ web: 'public' })} title={t('browser.web.public')} testid="browser-web-public">
            <span className="text-[12px] text-muted-foreground">{t('browser.web.publicDesc')}</span>
          </Choice>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="pr-down">{t('browser.profile.down')}</Label>
          <Select
            id="pr-down"
            value={p.on_exit_down}
            disabled={p.exit === 'direct'}
            onValueChange={(x) => set({ on_exit_down: x as 'wait' | 'vps' })}
            options={[
              { value: 'wait', label: t('browser.profile.downWait') },
              { value: 'vps', label: t('browser.profile.downVps') },
            ]}
          />
          <p className="text-[12px] text-muted-foreground">{t(p.on_exit_down === 'vps' ? 'browser.profile.downVpsHint' : 'browser.profile.downWaitHint')}</p>
        </div>
      </div>

      <div className="grid content-start gap-5">
        <section className="grid gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profile.usedBy')}</h3>
          <div className="divide-y rounded-lg border bg-card/60" data-testid="browser-used-by">
            {v.used_by.length ? (
              v.used_by.map((u) => {
                const o = ownerParts(u.path)
                return (
                  <div key={u.path} className="flex items-center gap-2 px-3 py-2 text-[13px]">
                    <Badge variant="muted">{t(`browser.kind.${u.kind}`)}</Badge>
                    <span className="min-w-0 flex-1 truncate">{o.name}</span>
                    <span className="text-[11px] text-muted-foreground">{t('browser.profile.chosenHere')}</span>
                  </div>
                )
              })
            ) : (
              <p className="px-3 py-2 text-[13px] text-muted-foreground">{p.id === 'main' ? t('browser.profile.mainUsers') : t('browser.profile.noUsers')}</p>
            )}
          </div>
          {v.used_by.length > 0 && <p className="text-[12px] text-muted-foreground">{t('browser.profile.inheritHint')}</p>}
        </section>
        <section className="grid gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profile.memory')}</h3>
          <div className="flex items-center gap-3 text-[13px]">
            <span className="min-w-0 flex-1">
              {b.state === 'running'
                ? t('browser.profile.on', { tabs: b.tabs.filter((x) => !x.asleep).length, mem: b.mem ? fmtBytes(b.mem) : '—' })
                : t('browser.profile.off', { tabs: b.tabs.length })}
            </span>
            {b.state === 'running' && (
              <Button size="sm" variant="outline" onClick={() => action.mutate({ profile: p.id, action: 'stop' })}>
                <Moon /> {t('browser.profile.sleep')}
              </Button>
            )}
          </div>
        </section>
        <section className="grid gap-2">
          <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.profile.danger')}</h3>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={forget} data-testid="browser-forget">
              <Eraser /> {t('browser.forget')}
            </Button>
            {p.id !== 'main' && (
              <Button size="sm" variant="outline" className="text-destructive" onClick={remove} data-testid="browser-profile-delete">
                <Trash2 /> {t('browser.profile.delete')}
              </Button>
            )}
          </div>
          <p className="text-[12px] text-muted-foreground">{t('browser.forgetDesc')}</p>
        </section>
        {mine && (
          <Link to={`/browser?nav=${encodeURIComponent(mine.id)}`} className="text-[12px] text-primary underline-offset-2 hover:underline">
            {t('browser.profile.backToLive', { exit: exitName(p.exit, exits, t) })}
          </Link>
        )}
      </div>
    </div>
  )
}

function ExitOption({ tone, name, line }: { tone: string; name: string; line: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span className={cn('size-1.5 shrink-0 rounded-full', tone)} />
      <span className="truncate">{name}</span>
      {line && <span className="truncate text-muted-foreground">· {line}</span>}
    </span>
  )
}

function Choice({ on, onPick, title, testid, children }: { on: boolean; onPick: () => void; title: string; testid: string; children?: React.ReactNode }) {
  return (
    <div className={cn('grid gap-2 rounded-lg border p-3', on ? 'border-primary/60 bg-primary/5' : 'bg-card/40')} data-testid={testid}>
      <button type="button" onClick={onPick} className="flex items-center gap-2 text-left text-[13px] font-medium" aria-pressed={on}>
        <span className={cn('flex size-4 items-center justify-center rounded-full border', on && 'border-primary')}>{on && <span className="size-2 rounded-full bg-primary" />}</span>
        {title}
      </button>
      {children}
    </div>
  )
}
