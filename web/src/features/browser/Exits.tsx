// Exits of the Harness Browser (Browser page -> an exit): where a profile's pages go out. Adding one = 4 choices
// explained (a phone: iPhone or Android, a rented proxy, a box / router with WireGuard, my computer later); each has its own
// page: a wizard for the phone (each step ticks itself when Harness sees it done), a form for the proxy and the box.
// "Test" says what the sites see: the address, its country and operator, its kind (internet provider, mobile network or
// datacenter - a rented proxy that is in fact a datacenter is said plainly), the delay and the speed.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { Check, ExternalLink, Globe, Laptop, Loader2, Router, Server, Smartphone, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserSetup, useBrowserStatus, useSaveExit, useTailscale, useTailscaleSet, useTestExit, type ExitInput } from '@/lib/queries'
import type { BrowserExit, BrowserExitKind, BrowserExitTest } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Badge, Button, confirm, Input, Label, SecretInput, Segmented, Textarea } from '@/components/ui'
import { QRCode } from '@/components/ui/qr-code'
import { Callout } from '@/features/common'
import { exitLine, exitTone } from './profiles'

// The Tailscale app of each phone: both can be an exit node (Exit Node -> Run as Exit Node).
const STORES = {
  ios: { url: 'https://apps.apple.com/app/tailscale/id1470499037', shown: 'apps.apple.com › Tailscale' },
  android: { url: 'https://play.google.com/store/apps/details?id=com.tailscale.ipn', shown: 'play.google.com › Tailscale' },
}
type Store = keyof typeof STORES
// An exit node is offered only once approved here (Machines -> ... -> Edit route settings -> Use as exit node).
const TS_MACHINES = 'https://login.tailscale.com/admin/machines'
const guessStore = (): Store => (/android/i.test(navigator.userAgent) ? 'android' : 'ios')

/** "Add an exit": the four ways, with what each needs, costs and shows to the sites. */
export function AddExit() {
  const t = useT()
  const nav = useNavigate()
  const save = useSaveExit()
  const add = (type: BrowserExitKind) =>
    save.mutate({ type, name: t(`browser.exit.kind.${type}`) }, { onSuccess: (e) => 'id' in e && nav(`/settings/browser?exit=${encodeURIComponent(e.id)}`) })
  const card = (key: BrowserExitKind | 'pc', Icon: typeof Globe, recommended = false) => (
    <button
      key={key}
      type="button"
      disabled={key === 'pc' || save.isPending}
      onClick={() => key !== 'pc' && add(key)}
      className={cn('grid gap-2 rounded-xl border bg-card p-4 text-left transition-colors hover:border-primary/60 disabled:cursor-not-allowed disabled:opacity-55', recommended && 'border-primary/50')}
      data-testid={`browser-add-exit-${key}`}
    >
      <span className="flex items-center gap-2 font-medium">
        <Icon className="size-4 text-primary" /> {t(`browser.add.${key}.title`)}
        {recommended && <Badge variant="success">{t('browser.add.recommended')}</Badge>}
        {key === 'pc' && <Badge variant="muted">{t('browser.add.soon')}</Badge>}
      </span>
      <span className="text-[13px] text-muted-foreground">{t(`browser.add.${key}.desc`)}</span>
      <span className="text-[12px] text-muted-foreground">{t(`browser.add.${key}.needs`)}</span>
    </button>
  )
  return (
    <div className="grid max-w-3xl gap-4" data-testid="browser-add-exit">
      <p className="text-[13px] text-muted-foreground">{t('browser.add.why')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {card('tailscale', Smartphone, true)}
        {card('proxy', Server)}
        {card('wireguard', Router)}
        {card('pc', Laptop)}
      </div>
      <p className="text-[12px] text-muted-foreground">{t('browser.add.never')}</p>
    </div>
  )
}

/** The result of a test: address, country, operator, kind, delay, speed. */
function TestResult({ test, className }: { test: BrowserExitTest | null | undefined; className?: string }) {
  const t = useT()
  if (!test) return null
  if (!test.ok)
    return (
      <Callout tone="warning" className={className}>
        {t('browser.test.failed', { why: test.error || '' })}
      </Callout>
    )
  const kindTone = test.kind === 'hosting' ? 'warning' : 'success'
  return (
    <div className={cn('grid gap-1.5 rounded-lg border bg-card p-3 text-[13px]', className)} data-testid="browser-test-result">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono">{test.ip}</span>
        {test.kind && <Badge variant={kindTone}>{t(`browser.test.kind.${test.kind}`)}</Badge>}
      </div>
      <span className="text-muted-foreground">{[test.operator, test.city, test.country].filter(Boolean).join(' · ')}{test.asn ? ` (${test.asn})` : ''}</span>
      <span className="text-muted-foreground">
        {test.latency_ms != null ? t('browser.test.delay', { ms: test.latency_ms }) : ''}
        {test.mbps != null ? ` · ${t('browser.test.speed', { mbps: test.mbps })}` : ''}
      </span>
      {test.kind === 'hosting' && <span className="text-warning">{t('browser.test.hostingWarn')}</span>}
    </div>
  )
}

/** "Test" + its last result. */
function TestBlock({ id, last }: { id: string; last: BrowserExitTest | null | undefined }) {
  const t = useT()
  const test = useTestExit()
  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => test.mutate(id)} loading={test.isPending} data-testid="browser-exit-test">
          {t('browser.test.run')}
        </Button>
        <span className="text-[12px] text-muted-foreground">{t('browser.test.hint')}</span>
      </div>
      <TestResult test={test.data || last} />
    </div>
  )
}

/** The server's own address. */
export function DirectPanel() {
  const t = useT()
  const { data: st } = useBrowserStatus()
  return (
    <div className="grid max-w-2xl gap-4" data-testid="browser-exit-direct">
      <Callout tone="warning">
        {t('browser.directWarn')}{' '}
        <Link to="/settings/browser?exit=new" className="text-primary underline">
          {t('browser.exit.add')}
        </Link>
      </Callout>
      <p className="text-[13px] text-muted-foreground">{t('browser.exit.directDesc')}</p>
      <TestBlock id="direct" last={st?.direct.test} />
    </div>
  )
}

/** One exit: its state, its settings (form or wizard), Test, Delete. */
export function ExitPanel({ exit }: { exit: BrowserExit }) {
  const t = useT()
  const nav = useNavigate()
  const save = useSaveExit()
  const { data: st } = useBrowserStatus()
  const users = (st?.profiles || []).filter((p) => p.exit === exit.id)
  const remove = async () => {
    if (!(await confirm({ title: t('browser.exit.deleteTitle', { name: exit.name }), description: t('browser.exit.deleteDesc'), destructive: true }))) return
    save.mutate({ id: exit.id, remove: true }, { onSuccess: () => nav('/settings/browser') })
  }
  return (
    <div className="grid max-w-3xl gap-5" data-testid="browser-exit">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className={cn('size-2 rounded-full', exitTone(exit))} />
        <span>{t(`browser.exit.state.${exit.state}`)}</span>
        <span className="text-muted-foreground">{exitLine(exit, t)}</span>
        {exit.error && exit.state === 'down' && <span className="min-w-0 text-warning [overflow-wrap:anywhere]">· {exit.error}</span>}
      </div>
      <NameField exit={exit} />
      {exit.type === 'tailscale' && <TailscaleWizard exit={exit} />}
      {exit.type === 'proxy' && <ProxyForm exit={exit} />}
      {exit.type === 'wireguard' && <WireGuardForm exit={exit} />}
      {exit.type !== 'tailscale' && <TestBlock id={exit.id} last={exit.test} />}
      <div className="grid gap-2 border-t pt-4">
        <p className="text-[12px] text-muted-foreground">
          {users.length ? t('browser.exit.usedBy', { names: users.map((p) => p.name || t('browser.mainProfile')).join(', ') }) : t('browser.exit.unused')}
        </p>
        <div>
          <Button size="sm" variant="ghost" className="text-destructive" onClick={remove} disabled={users.length > 0} data-testid="browser-exit-delete">
            <Trash2 /> {t('browser.exit.delete')}
          </Button>
        </div>
      </div>
    </div>
  )
}

function NameField({ exit }: { exit: BrowserExit }) {
  const t = useT()
  const save = useSaveExit()
  const [name, setName] = React.useState(exit.name)
  React.useEffect(() => setName(exit.name), [exit.name])
  return (
    <div className="grid max-w-sm gap-1.5">
      <Label htmlFor="exit-name">{t('browser.exit.name')}</Label>
      <Input id="exit-name" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== exit.name && save.mutate({ id: exit.id, name: name.trim() })} maxLength={40} />
    </div>
  )
}

/** Tools (Tailscale, wireproxy) missing on the server: one button installs them. */
function ToolsMissing() {
  const t = useT()
  const setup = useBrowserSetup()
  const { data: st } = useBrowserStatus()
  return (
    <Callout tone="info" title={t('browser.exit.toolsTitle')} action={<Button size="sm" onClick={() => setup.mutate({ exits: true })} loading={setup.isPending || st?.setup.running}>{t('browser.setup')}</Button>}>
      {t('browser.exit.toolsDesc')}
      {st?.setup.error && <span className="mt-1 block text-destructive">{st.setup.error}</span>}
    </Callout>
  )
}

function ProxyForm({ exit }: { exit: BrowserExit }) {
  const t = useT()
  const save = useSaveExit()
  const [v, setV] = React.useState<ExitInput>({ url: exit.url || '', user: exit.user || '', secret: '' })
  const dirty = v.url !== (exit.url || '') || v.user !== (exit.user || '') || !!v.secret
  return (
    <form
      className="grid max-w-xl gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ id: exit.id, url: v.url?.trim(), user: v.user?.trim(), ...(v.secret ? { secret: v.secret } : {}) }, { onSuccess: () => setV((x) => ({ ...x, secret: '' })) })
      }}
      data-testid="browser-proxy-form"
    >
      <p className="text-[13px] text-muted-foreground">{t('browser.proxy.desc')}</p>
      <div className="grid gap-1.5">
        <Label htmlFor="px-url">{t('browser.proxy.url')}</Label>
        <Input id="px-url" value={v.url} onChange={(e) => setV({ ...v, url: e.target.value })} placeholder="socks5://proxy.example.net:1080" className="font-mono text-[13px]" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="px-user">{t('browser.proxy.user')}</Label>
          <Input id="px-user" value={v.user} onChange={(e) => setV({ ...v, user: e.target.value })} autoComplete="off" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="px-pass">{t('browser.proxy.password')}</Label>
          <SecretInput id="px-pass" value={v.secret} onValueChange={(x) => setV({ ...v, secret: x })} placeholder={exit.secret ? t('browser.proxy.kept') : ''} />
        </div>
      </div>
      <p className="text-[12px] text-muted-foreground">{t('browser.proxy.vault')}</p>
      <div>
        <Button size="sm" type="submit" disabled={!dirty} loading={save.isPending}>
          {t('common.save')}
        </Button>
      </div>
    </form>
  )
}

function WireGuardForm({ exit }: { exit: BrowserExit }) {
  const t = useT()
  const save = useSaveExit()
  const { data: st } = useBrowserStatus()
  const [conf, setConf] = React.useState('')
  return (
    <div className="grid max-w-xl gap-3" data-testid="browser-wireguard-form">
      <p className="text-[13px] text-muted-foreground">{t('browser.wireguard.desc')}</p>
      {st && !st.tools.wireguard && <ToolsMissing />}
      <div className="grid gap-1.5">
        <Label htmlFor="wg-conf">{t('browser.wireguard.config')}</Label>
        <Textarea id="wg-conf" value={conf} onChange={(e) => setConf(e.target.value)} rows={8} placeholder={exit.secret ? t('browser.wireguard.kept') : '[Interface]\nPrivateKey = …\nAddress = …\n\n[Peer]\nPublicKey = …\nEndpoint = …'} className="font-mono text-[12px]" spellCheck={false} />
      </div>
      <p className="text-[12px] text-muted-foreground">{t('browser.wireguard.where')}</p>
      <div>
        <Button size="sm" disabled={!conf.includes('[Interface]')} loading={save.isPending} onClick={() => save.mutate({ id: exit.id, secret: conf }, { onSuccess: () => setConf('') })}>
          {t('common.save')}
        </Button>
      </div>
    </div>
  )
}

/** The phone (or a box, an Apple TV) over Tailscale: four steps, each ticked when Harness sees it done. */
function TailscaleWizard({ exit }: { exit: BrowserExit }) {
  const t = useT()
  const { data: st } = useBrowserStatus()
  const tools = !!st?.tools.tailscale
  const { data: ts } = useTailscale(tools ? exit.id : undefined, 3000)
  const set = useTailscaleSet()
  const test = useTestExit()
  const [advanced, setAdvanced] = React.useState(!!exit.login_server)
  const [store, setStore] = React.useState<Store>(guessStore)
  const save = useSaveExit()
  const [server, setServer] = React.useState(exit.login_server || '')
  const linked = !!ts && !['needs_setup', 'needs_login', 'starting'].includes(ts.state)
  const nodes = ts?.nodes || []
  const chosen = ts?.node
  const step = !tools ? 1 : !linked ? 2 : !nodes.some((n) => n.online) && !chosen ? 3 : 4
  const done = (n: number) => step > n || (n === 4 && ts?.state === 'up' && !!(test.data?.ok || exit.test?.ok))
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]" data-testid="browser-tailscale">
      <ol className="grid gap-0">
        <Step n={1} done={done(1)} current={step === 1} title={t('browser.ts.s1')} >
          {step === 1 ? <ToolsMissing /> : <span>{t('browser.ts.s1done')}</span>}
        </Step>
        <Step n={2} done={done(2)} current={step === 2} title={t('browser.ts.s2')}>
          {linked ? (
            <span>{t('browser.ts.s2done', { account: ts?.account || '' })}</span>
          ) : (
            <div className="grid gap-2">
              <span>{t('browser.ts.s2desc')}</span>
              {ts?.auth_url ? (
                <div>
                  <Button size="sm" asChild>
                    <a href={ts.auth_url} target="_blank" rel="noreferrer" data-testid="browser-ts-login">
                      {t('browser.ts.login')} <ExternalLink />
                    </a>
                  </Button>
                </div>
              ) : (
                <span className="inline-flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" /> {t('browser.ts.preparing')}
                </span>
              )}
            </div>
          )}
        </Step>
        <Step n={3} done={done(3)} current={step === 3} title={t('browser.ts.s3')}>
          <div className="grid gap-1">
            <span>{t('browser.ts.s3a')}</span>
            <span>{t('browser.ts.s3b')}</span>
            <span>{t('browser.ts.s3c')}</span>
            <span>{t('browser.ts.s3d')}</span>
            {!exit.login_server && <span>{t('browser.ts.s3e')}</span>}
            {step === 3 && !!ts?.unapproved?.length && (
              <div className="mt-1 grid gap-2 rounded-md border border-warning/40 bg-warning/8 px-2.5 py-2" data-testid="browser-ts-unapproved">
                <span>{t('browser.ts.unapproved', { names: ts.unapproved.map((n) => (n.name === 'localhost' ? n.os : n.name)).join(', ') })}</span>
                {!exit.login_server && (
                  <div>
                    <Button size="sm" variant="outline" asChild>
                      <a href={TS_MACHINES} target="_blank" rel="noreferrer">
                        {t('browser.ts.approve')} <ExternalLink />
                      </a>
                    </Button>
                  </div>
                )}
              </div>
            )}
            {step === 3 && (
              <span className="mt-1 inline-flex items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-muted-foreground">
                <span className="size-1.5 animate-pulse rounded-full bg-warning" /> {t('browser.ts.waitingPhone')}
              </span>
            )}
          </div>
        </Step>
        <Step n={4} done={done(4)} current={step === 4} title={t('browser.ts.s4')} last>
          {step === 4 && (
            <div className="grid gap-2">
              <span>{t('browser.ts.s4desc')}</span>
              <div className="grid gap-1">
                {nodes.map((n) => (
                  <button
                    key={n.id}
                    type="button"
                    disabled={!n.online || set.isPending}
                    onClick={() => set.mutate({ id: exit.id, node: n.id }, { onSuccess: () => test.mutate(exit.id) })}
                    className={cn('flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left hover:bg-accent disabled:opacity-50', n.active && 'border-primary bg-primary/8')}
                    data-testid="browser-ts-node"
                  >
                    <span className={cn('size-1.5 rounded-full', n.online ? 'bg-success' : 'bg-muted-foreground/50')} />
                    <span className="min-w-0 flex-1 truncate">{n.name}</span>
                    <span className="text-[12px] text-muted-foreground">{n.os}</span>
                    {n.active && <Check className="size-3.5 text-primary" />}
                  </button>
                ))}
              </div>
              {ts?.state === 'node_offline' && <span className="text-warning">{t('browser.ts.nodeOffline')}</span>}
              {chosen && (
                <div>
                  <Button size="sm" variant="outline" onClick={() => test.mutate(exit.id)} loading={test.isPending}>
                    {t('browser.test.run')}
                  </Button>
                </div>
              )}
              <TestResult test={test.data || exit.test} />
            </div>
          )}
        </Step>
      </ol>
      <div className="grid content-start gap-3">
        <div className="grid justify-items-center gap-2 rounded-xl border bg-card p-4 text-center text-[12px]">
          <Segmented
            size="sm"
            value={store}
            onChange={setStore}
            aria-label={t('browser.ts.phone')}
            options={[
              { value: 'ios', label: 'iPhone' },
              { value: 'android', label: 'Android' },
            ]}
          />
          <QRCode value={STORES[store].url} className="size-32" label={t(`browser.ts.qr.${store}`)} />
          <span className="font-medium">{t(`browser.ts.qr.${store}`)}</span>
          <span className="text-muted-foreground">{STORES[store].shown}</span>
        </div>
        <div className="grid gap-1.5 rounded-xl border bg-card p-4 text-[12px]">
          <span className="font-medium">{t('browser.ts.good')}</span>
          <span className="text-muted-foreground">{t('browser.ts.good1')}</span>
          <span className="text-muted-foreground">{t(`browser.ts.good2.${store}`)}</span>
          <span className="text-muted-foreground">{t('browser.ts.good3')}</span>
        </div>
        {advanced ? (
          <div className="grid gap-1.5 text-[12px]">
            <Label htmlFor="ts-server">{t('browser.ts.headscale')}</Label>
            <Input id="ts-server" value={server} onChange={(e) => setServer(e.target.value)} onBlur={() => server !== (exit.login_server || '') && save.mutate({ id: exit.id, login_server: server.trim() })} placeholder="https://headscale.example.com" className="font-mono text-[12px]" />
          </div>
        ) : (
          <button type="button" className="text-left text-[12px] text-muted-foreground underline-offset-2 hover:underline pointer-coarse:min-h-10" onClick={() => setAdvanced(true)}>
            {t('browser.ts.advanced')}
          </button>
        )}
        {linked && (
          <button type="button" className="text-left text-[12px] text-muted-foreground underline-offset-2 hover:underline pointer-coarse:min-h-10" onClick={() => set.mutate({ id: exit.id, action: 'logout' })}>
            {t('browser.ts.logout')}
          </button>
        )}
      </div>
    </div>
  )
}

function Step({ n, done, current, title, last, children }: { n: number; done: boolean; current: boolean; title: string; last?: boolean; children: React.ReactNode }) {
  return (
    <li className={cn('grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 py-3', !last && 'border-b', !done && !current && 'opacity-55')} data-testid={`browser-ts-step-${n}`} data-done={done}>
      <span className={cn('flex size-6 items-center justify-center rounded-full text-[12px] font-semibold', done ? 'bg-success/15 text-success' : current ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
        {done ? <Check className="size-3.5" /> : n}
      </span>
      <div className="grid min-w-0 gap-1 text-[13px]">
        <span className="font-medium">{title}</span>
        <div className="text-muted-foreground">{children}</div>
      </div>
    </li>
  )
}

