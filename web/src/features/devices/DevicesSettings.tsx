// Settings -> Devices (/settings/devices): the switch, the devices waiting for the user's OK (Accept / Refuse), "Add a
// device" (a one-time code: the command for a computer, a QR code for a phone), every device (online, what Claude may
// do, who may use it, Watch, Rename, Remove) and the last actions. ?watch=<id> opens a device's live window (the link
// of a request's notification); ?add=1 opens "Add a device".
import * as React from 'react'
import { useSearchParams } from 'react-router'
import { Download, EllipsisVertical, Eye, Laptop, MonitorSmartphone, Pencil, Plus, Smartphone, Trash2 } from 'lucide-react'
import { useLang, useT, type TFn, type TKey } from '@/i18n'
import { useConfirmDevice, useDevices, useNewInvite, useRemoveDevice, useSaveDevice, useSettings, useWorkspace } from '@/lib/queries'
import type { Device, DeviceAction, DeviceInvite, DeviceOs, DevicesStatus } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge, Button, Checkbox, CopyButton, Dialog, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Segmented, Select, Skeleton, StatusDot, confirm } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Callout } from '@/features/common'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'
import { DevicesFeature } from './DevicesFeature'
import { DeviceWindow } from './DeviceWindow'
import { ScreenPick } from './DeviceLive'

type Tab = 'windows' | 'darwin' | 'linux' | 'android'

export function DevicesSettingsSection() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const { data: s } = useSettings()
  const on = !!s?.devices_feature
  const [adding, setAdding] = React.useState(params.get('add') === '1')
  const { data: st } = useDevices(on, adding ? 2000 : false)
  const watch = params.get('watch') || ''
  const watched = st?.devices.find((d) => d.id === watch)
  const setWatch = (id: string | null) =>
    setParams((p) => {
      const next = new URLSearchParams(p)
      if (id) next.set('watch', id)
      else next.delete('watch')
      return next
    }, { replace: true })

  if (!on) return <SectionStack><DevicesFeature /></SectionStack>
  if (!st) return <SectionStack><DevicesFeature /><Skeleton className="h-40" /></SectionStack>
  const waiting = st.devices.filter((d) => !d.confirmed)
  const devices = st.devices.filter((d) => d.confirmed)
  return (
    <SectionStack>
      <DevicesFeature />
      {waiting.map((d) => <Waiting key={d.id} d={d} />)}
      <SettingsCard
        title={devices.length ? t('devices.list.count', { count: devices.length }) : t('devices.list.title')}
        actions={
          <Button size="sm" onClick={() => setAdding(true)} data-testid="devices-add">
            <Plus /> {t('devices.add')}
          </Button>
        }
      >
        {devices.length ? (
          <>
            <div className="divide-y" data-testid="devices-list">
              {devices.map((d) => <Row key={d.id} d={d} st={st} onWatch={() => setWatch(d.id)} />)}
            </div>
            <p className="mt-4 border-t pt-3 text-[12px] text-muted-foreground">{t('devices.access.agentsNote')}</p>
          </>
        ) : (
          <p className="py-2 text-[13px] text-muted-foreground">{t('devices.empty')}</p>
        )}
      </SettingsCard>
      <Actions st={st} />
      <AddDevice open={adding} onOpenChange={setAdding} st={st} />
      {watch && <DeviceWindow id={watch} name={watched?.name} open onOpenChange={(v) => !v && setWatch(null)} />}
    </SectionStack>
  )
}

function DeviceIcon({ os, className }: { os: DeviceOs; className?: string }) {
  const I = os === 'android' ? Smartphone : Laptop
  return <I className={cn('size-4 shrink-0', className)} />
}

/** A device that paired and waits: Accept / Refuse (a code seen by someone else cannot plug a device in silently). */
function Waiting({ d }: { d: Device }) {
  const t = useT()
  const answer = useConfirmDevice()
  return (
    <Callout
      tone="warning"
      icon={MonitorSmartphone}
      title={t('devices.new.title', { name: d.name, os: d.os_name })}
      action={
        <div className="flex gap-2">
          <Button size="sm" loading={answer.isPending && answer.variables?.ok} onClick={() => answer.mutate({ id: d.id, ok: true })} data-testid="device-accept">
            {t('devices.accept')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => answer.mutate({ id: d.id, ok: false })} data-testid="device-refuse">
            {t('devices.refuse')}
          </Button>
        </div>
      }
    >
      {t('devices.new.desc', { ip: d.ip || '?' })}
    </Callout>
  )
}

function Row({ d, st, onWatch }: { d: Device; st: DevicesStatus; onWatch: () => void }) {
  const t = useT()
  const lang = useLang()
  const save = useSaveDevice()
  const remove = useRemoveDevice()
  const [renaming, setRenaming] = React.useState(false)
  const note = d.hello?.note || d.note
  const outdated = !!st.latest && !!d.version && cmpVersion(d.version, st.latest) < 0
  const several = (d.hello?.screens ?? d.screens ?? []).length > 1
  const state = d.paused ? t('devices.paused') : d.human ? t('devices.human') : d.claude ? t('devices.claude') : d.online ? t('devices.online') : t('devices.offline', { ago: fmtRelative(d.last_seen, lang) })
  return (
    <div className="grid gap-3 py-4 first:pt-0 last:pb-0" data-testid="device-row">
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted">
          <DeviceIcon os={d.os} className="text-muted-foreground" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="truncate text-sm font-medium">{d.name}</span>
          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-[12px] text-muted-foreground">
            <span>{d.os_name}{d.version ? ` · ${d.version}` : ''}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1.5">
              <StatusDot tone={d.online ? (d.claude ? 'running' : 'ok') : 'idle'} pulse={d.claude} /> {state}
            </span>
          </span>
        </div>
        <Button size="sm" variant="outline" className="shrink-0" disabled={!d.online} onClick={onWatch} data-testid="device-watch">
          <Eye /> <span className="max-sm:sr-only">{t('devices.watch')}</span>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" className="shrink-0" aria-label={t('devices.more')} title={t('devices.more')} data-testid="device-menu">
              <EllipsisVertical />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setRenaming(true)}>
              <Pencil /> {t('devices.rename')}
            </DropdownMenuItem>
            <DropdownMenuItem
              destructive
              data-testid="device-remove"
              onSelect={async () => {
                if (await confirm({ title: t('devices.remove.title', { name: d.name }), description: t('devices.remove.desc'), destructive: true, confirmText: t('devices.remove') }))
                  remove.mutate(d.id)
              }}
            >
              <Trash2 /> {t('devices.remove')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {!d.online && <p className="text-[12px] text-muted-foreground sm:pl-12">{t(d.os === 'android' ? 'devices.offlineHelp.android' : 'devices.offlineHelp')}</p>}
      <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-[10rem_minmax(0,1fr)] sm:items-start sm:pl-12">
        <Field label={t('devices.mode.label')} hint={d.mode === 'view' ? t('devices.mode.viewDesc') : undefined}>
          <Segmented
            size="sm"
            value={d.mode}
            onChange={(mode) => save.mutate({ id: d.id, mode })}
            aria-label={t('devices.mode.label')}
            options={[
              { value: 'view', label: t('devices.mode.view') },
              { value: 'control', label: t('devices.mode.control') },
            ]}
          />
        </Field>
        {several && (
          <Field label={t('devices.live.screen')} hint={t('devices.live.screenHelp')}>
            <ScreenPick d={d} />
          </Field>
        )}
        <Field label={t('devices.access.label')}>
          <Access d={d} />
        </Field>
      </dl>
      {note && <p className="text-[12px] text-warning sm:pl-12">{t('devices.note', { note })}</p>}
      {outdated && <p className="text-[12px] text-muted-foreground sm:pl-12">{t('devices.outdated', { version: st.latest })}</p>}
      <Rename d={d} open={renaming} onOpenChange={setRenaming} />
    </div>
  )
}

/** One setting of a device: its label on the left (above on a phone), the control and a hint on the right. */
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-[12px] text-muted-foreground sm:pt-2">{label}</dt>
      <dd className="-mt-2 grid min-w-0 justify-items-start gap-1.5 sm:mt-0">
        {children}
        {hint && <p className="text-[12px] text-muted-foreground">{hint}</p>}
      </dd>
    </>
  )
}

function cmpVersion(a: string, b: string): number {
  const pa = a.replace(/^v/, '').split(/[.+-]/).map((x) => parseInt(x, 10) || 0)
  const pb = b.replace(/^v/, '').split(/[.+-]/).map((x) => parseInt(x, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0)
  return 0
}

/** Who may use it: every project and agent, or the projects chosen (agents also need it in their own settings). */
function Access({ d }: { d: Device }) {
  const t = useT()
  const save = useSaveDevice()
  const { data: ws } = useWorkspace()
  const all = d.scope.includes('*')
  const projects = d.scope.filter((x) => x.startsWith('project:')).map((x) => x.slice(8))
  const agents = d.scope.filter((x) => x.startsWith('agent:'))
  const set = (scope: string[]) => save.mutate({ id: d.id, scope })
  return (
    <>
      <Select
        className="h-8 w-60 text-[13px] max-sm:w-full"
        value={all ? 'all' : 'some'}
        onValueChange={(v) => set(v === 'all' ? ['*'] : [...agents])}
        aria-label={t('devices.access.label')}
        options={[
          { value: 'all', label: t('devices.access.all') },
          { value: 'some', label: projects.length ? t('devices.access.count', { count: projects.length }) : t('devices.access.some') },
        ]}
      />
      {!all && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-0.5" data-testid="device-projects">
          {(ws?.projects || []).map((p) => (
            <label key={p.name} className="flex cursor-pointer items-center gap-1.5 text-[12px] pointer-coarse:min-h-10">
              <Checkbox
                checked={projects.includes(p.name)}
                onCheckedChange={(c) => set([...d.scope.filter((x) => x !== `project:${p.name}` && x !== '*'), ...(c ? [`project:${p.name}`] : [])])}
              />
              {p.name}
            </label>
          ))}
          {!projects.length && !agents.length && <span className="text-[12px] text-muted-foreground">{t('devices.access.none')}</span>}
        </div>
      )}
    </>
  )
}

function Rename({ d, open, onOpenChange }: { d: Device; open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT()
  const save = useSaveDevice()
  const [name, setName] = React.useState(d.name)
  React.useEffect(() => {
    if (open) setName(d.name)
  }, [open, d.name])
  const submit = () => name.trim() && save.mutate({ id: d.id, name: name.trim() }, { onSuccess: () => onOpenChange(false) })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('devices.rename.title')}</DialogTitle>
          <DialogDescription className="sr-only">{d.name}</DialogDescription>
        </DialogHeader>
        <Input value={name} maxLength={64} autoFocus onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button loading={save.isPending} disabled={!name.trim()} onClick={submit}>{t('devices.rename')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function useCountdown(until: number | undefined): number {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    if (!until) return
    const i = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(i)
  }, [until])
  return until ? Math.max(0, Math.round(until - now)) : 0
}

const TARGET_OF: Record<Tab, string[]> = {
  windows: ['windows-amd64', 'windows-arm64'],
  darwin: ['darwin-arm64', 'darwin-amd64'],
  linux: ['linux-amd64', 'linux-arm64'],
  android: ['android'],
}

/** A one-time code, the command or the QR code of each system, a countdown; the device that pairs shows up here. */
function AddDevice({ open, onOpenChange, st }: { open: boolean; onOpenChange: (v: boolean) => void; st: DevicesStatus }) {
  const t = useT()
  const make = useNewInvite()
  const [inv, setInv] = React.useState<DeviceInvite | null>(null)
  const [tab, setTab] = React.useState<Tab>(() => (/Android/i.test(navigator.userAgent) ? 'android' : /Mac/i.test(navigator.platform) ? 'darwin' : /Win/i.test(navigator.platform) ? 'windows' : 'linux'))
  const known = React.useRef<Set<string>>(new Set())
  const left = useCountdown(inv?.expires_at)
  const fresh = React.useCallback(() => make.mutate({}, { onSuccess: setInv }), [make])
  React.useEffect(() => {
    if (!open) return setInv(null)
    known.current = new Set(st.devices.map((d) => d.id))
    fresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  // the device paired from this dialog: waiting for the OK, then accepted (the dialog says so instead of waiting again)
  const arrived = open ? st.devices.filter((d) => !known.current.has(d.id)) : []
  const pending = arrived.filter((d) => !d.confirmed)
  const ready = arrived.filter((d) => d.confirmed)
  const done = ready.length > 0 && pending.length === 0
  const available = TARGET_OF[tab].some((x) => st.available.includes(x))
  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="devices-add-dialog">
        <DialogHeader>
          <DialogTitle>{t('devices.add')}</DialogTitle>
          <DialogDescription>{t('devices.add.desc')}</DialogDescription>
        </DialogHeader>
        <Segmented
          value={tab}
          onChange={setTab}
          aria-label={t('devices.add')}
          options={[
            { value: 'windows', label: t('devices.add.windows') },
            { value: 'darwin', label: t('devices.add.mac') },
            { value: 'linux', label: t('devices.add.linux') },
            { value: 'android', label: t('devices.add.android') },
          ]}
        />
        {!available && !done && <Callout tone="info">{t('devices.add.notAvailable')}</Callout>}
        {done ? (
          <div className="grid gap-2" data-testid="devices-add-ready">
            {ready.map((d) => (
              <Callout key={d.id} tone="success" icon={d.kind === 'android' ? Smartphone : Laptop} title={t('devices.add.ready', { name: d.name })}>
                {t(d.kind === 'android' ? 'devices.add.readyPhone' : 'devices.add.readyDesc')}
              </Callout>
            ))}
          </div>
        ) : !inv ? (
          <Skeleton className="h-28" />
        ) : left <= 0 ? (
          <Callout tone="warning" action={<Button size="sm" variant="outline" onClick={fresh}>{t('devices.add.again')}</Button>}>
            {t('devices.add.expired')}
          </Callout>
        ) : tab === 'android' ? (
          <div className="grid gap-3 sm:grid-cols-[auto_minmax(0,1fr)]" data-testid="devices-add-phone">
            <div className="grid content-start justify-items-center gap-2">
              <QRCode value={inv.link} className="size-44 p-1" label={inv.link} />
              {inv.downloads.android && (
                <Button asChild variant="outline" size="sm" className="w-full" data-testid="devices-add-apk">
                  <a href={inv.downloads.android} download="harness-link.apk">
                    <Download /> {t('devices.add.apk')}
                  </a>
                </Button>
              )}
            </div>
            <div className="grid content-start gap-2 text-[13px]">
              <p>{t('devices.add.phone')}</p>
              <p className="text-muted-foreground">{t('devices.add.phoneHelp')}</p>
              <p className="text-muted-foreground">{t('devices.add.apkHelp')}</p>
              <p className="text-muted-foreground">{t('devices.add.manual')}</p>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
                <dt className="text-muted-foreground">{t('devices.add.server')}</dt>
                <dd className="truncate font-mono text-[12px]">{inv.server}</dd>
                <dt className="text-muted-foreground">{t('devices.add.code')}</dt>
                <dd className="font-mono text-[15px] tracking-widest">{inv.code}</dd>
              </dl>
            </div>
          </div>
        ) : (
          <div className="grid gap-2 text-[13px]" data-testid="devices-add-command">
            <p>{t(tab === 'windows' ? 'devices.add.cmdWindows' : tab === 'darwin' ? 'devices.add.cmdMac' : 'devices.add.cmdLinux')}</p>
            <div className="flex min-w-0 items-center gap-2 rounded-md border bg-muted py-1 pr-1 pl-3 font-mono text-[12px]">
              <code className="min-w-0 flex-1 break-all">{tab === 'windows' ? inv.commands.ps1 : inv.commands.sh}</code>
              <CopyButton text={tab === 'windows' ? inv.commands.ps1 : inv.commands.sh} />
            </div>
            <p className="text-muted-foreground">{t('devices.add.after')}</p>
            {tab === 'darwin' && <p className="text-muted-foreground">{t('devices.add.macHelp')}</p>}
          </div>
        )}
        {inv && left > 0 && !done && (
          <p className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
            <Badge variant="muted">{t('devices.add.expires', { time: mmss })}</Badge> {t('devices.add.secret')}
          </p>
        )}
        {pending.length ? pending.map((d) => <Waiting key={d.id} d={d} />) : !done && inv && left > 0 && <p className="text-[12px] text-muted-foreground">{t('devices.add.waiting')}</p>}
        {done && (
          <DialogFooter>
            <Button onClick={() => onOpenChange(false)} data-testid="devices-add-done">{t('devices.add.done')}</Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Actions({ st }: { st: DevicesStatus }) {
  const t = useT()
  const lang = useLang()
  const [all, setAll] = React.useState(false)
  const devs = Object.fromEntries(st.devices.map((d) => [d.id, d]))
  if (!st.actions.length) return null
  const shown = st.actions.slice(0, all ? 50 : 8)
  return (
    <SettingsCard title={t('devices.actions.title')} description={t('devices.actions.desc')}>
      <ul className="grid divide-y" data-testid="devices-actions">
        {shown.map((a, i) => {
          const d = devs[a.device]
          return (
            <li key={i} className="flex min-w-0 items-center gap-3 py-2 text-[13px] first:pt-0 last:pb-0">
              <StatusDot tone={a.ok ? 'ok' : 'error'} />
              <span className="min-w-0 flex-1">
                <span className={cn(!a.ok && 'text-destructive')}>{actionText(t, a)}</span>
                {a.error && <span className="block truncate text-[12px] text-muted-foreground">{a.error}</span>}
              </span>
              <span className="hidden max-w-40 shrink-0 truncate text-[12px] text-muted-foreground sm:block">
                {d ? d.name : t('devices.actions.removed')}
              </span>
              <span className="w-20 shrink-0 text-right text-[12px] text-muted-foreground tabular-nums">{fmtRelative(a.at, lang)}</span>
            </li>
          )
        })}
      </ul>
      {st.actions.length > 8 && (
        <Button size="sm" variant="ghost" className="mt-2 -ml-2" onClick={() => setAll(!all)}>
          {all ? t('devices.actions.less') : t('devices.actions.more')}
        </Button>
      )}
    </SettingsCard>
  )
}

/** One of Claude's actions in plain words ("Clicked at 490, 226", "Typed 5 characters"). */
function actionText(t: TFn, a: DeviceAction): string {
  const g = a.args || {}
  const chars = /<(\d+) chars>/.exec(g.text || '')?.[1]
  switch (a.tool) {
    case 'click':
      return t(g.double === 'True' ? 'devices.act.double' : 'devices.act.click', { x: g.x, y: g.y })
    case 'type':
      return t('devices.act.type', { count: Number(chars || 0) })
    case 'key':
      return t('devices.act.key', { keys: g.keys || '' })
    case 'open_app':
      return g.name || g.app ? t('devices.act.openNamed', { name: g.name || g.app }) : t('devices.act.open')
    case 'wait':
      return t('devices.act.wait', { s: g.s || '' })
    case 'screen':
      return t('devices.act.screen', { n: g.screen === '-1' ? t('devices.live.main') : g.screen })
    case 'screenshot': case 'zoom': case 'scroll': case 'drag': case 'move': case 'long_press': case 'ui_tree':
    case 'tap_element': case 'set_text': case 'apps': case 'ask_human': case 'devices':
      return t(`devices.act.${a.tool}` as TKey)
    default:
      return a.tool
  }
}
