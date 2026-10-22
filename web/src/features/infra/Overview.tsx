// Overview tab of the Infra page: how the page works (hideable), the counts, what to look at, and every source Harness
// reads with what to do when one is missing (a key, a right, a server to connect).
import * as React from 'react'
import { Link } from 'react-router'
import { ArrowUpRight, BellRing, BookOpen, Eye, KeyRound, MessageSquarePlus, Plug, ServerCog, X } from 'lucide-react'
import type { InfraResource, InfraSource, InfraView } from '@/lib/types'
import { tDyn, useT } from '@/i18n'
import { Badge, Button, StatusDot } from '@/components/ui'
import { cn, store } from '@/lib/utils'
import { KIND_ICON, PLATFORMS, locationLabel } from './shared'

function DocLink({ className }: { className?: string }) {
  const t = useT()
  return (
    <Link to="/docs/infra" className={cn('inline-flex items-center gap-1 text-xs text-primary hover:underline pointer-coarse:min-h-10', className)}>
      <BookOpen className="size-3.5" /> {t('infra.docs')}
    </Link>
  )
}

const HOW_KEY = 'mx.infra.howHidden'

export function useHowItWorks() {
  const [hidden, setHidden] = React.useState(() => store.get(HOW_KEY) === '1')
  const set = (h: boolean) => {
    store.set(HOW_KEY, h ? '1' : '0')
    setHidden(h)
  }
  return { hidden, hide: () => set(true), show: () => set(false) }
}

export function HowItWorks({ onHide }: { onHide: () => void }) {
  const t = useT()
  const steps = [
    { icon: Eye, title: t('infra.how.readTitle'), body: t('infra.how.read') },
    { icon: BellRing, title: t('infra.how.watchTitle'), body: t('infra.how.watch') },
    { icon: MessageSquarePlus, title: t('infra.how.createTitle'), body: t('infra.how.create') },
  ]
  return (
    <section className="relative grid gap-3 rounded-xl border border-primary/25 bg-primary/5 p-4" data-testid="infra-how">
      <div className="flex items-start gap-2 pr-8">
        <h2 className="text-sm font-semibold">{t('infra.how.title')}</h2>
      </div>
      <Button variant="ghost" size="icon" className="absolute top-2 right-2 size-7 pointer-coarse:size-10" onClick={onHide} aria-label={t('infra.how.hide')} title={t('infra.how.hide')}>
        <X />
      </Button>
      <ol className="grid gap-3 md:grid-cols-3">
        {steps.map((s, i) => (
          <li key={i} className="grid content-start gap-1.5 rounded-lg bg-card/60 p-3">
            <span className="flex items-center gap-2 text-[13px] font-medium">
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-primary/15 text-primary">
                <s.icon className="size-3.5" />
              </span>
              {s.title}
            </span>
            <p className="text-[13px] leading-relaxed text-muted-foreground">{s.body}</p>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="min-w-0 flex-1 text-xs text-muted-foreground">{t('infra.how.examples')}</p>
        <DocLink />
      </div>
    </section>
  )
}

const PROVIDER_LINKS = {
  cloudflare: 'https://dash.cloudflare.com/profile/api-tokens',
  hostinger: 'https://hpanel.hostinger.com/profile/api',
}

function SourceRow({ tone, title, what, children, muted }: { tone: 'ok' | 'warn' | 'error' | 'idle'; title: React.ReactNode; what: string; children?: React.ReactNode; muted?: boolean }) {
  return (
    <li className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2.5', muted ? 'border-dashed' : 'bg-card')}>
      <StatusDot tone={tone} />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-[13px] font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{what}</span>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2 text-xs">{children}</div>}
    </li>
  )
}

/** Every source of the snapshot, what it gives, and the next step when it is missing or partial. */
export function SourcesPanel({ v, all, onServers }: { v: InfraView; all: InfraResource[]; onServers: () => void }) {
  const t = useT()
  const servers = Object.entries(v.sources.servers || {})
  const notRead = all.filter((r) => r.kind === 'server' && r.details.not_connected)
  const provider = (name: 'cloudflare' | 'hostinger', s?: InfraSource) => {
    const missing = Object.entries(s?.sections || {}).filter(([, x]) => x && x !== 'ok').map(([k]) => tDyn(t, `infra.section.${k}`, k))
    const label = name === 'cloudflare' ? 'Cloudflare' : 'Hostinger'
    if (!s?.connected)
      return (
        <SourceRow key={name} tone="idle" title={label} what={t(`infra.src.${name}`)}>
          <Button variant="outline" size="sm" asChild>
            <Link to="/settings/keys">
              <KeyRound /> {t('infra.src.addKey', { key: name === 'cloudflare' ? 'CLOUDFLARE_API_TOKEN' : 'HOSTINGER_API_TOKEN' })}
            </Link>
          </Button>
        </SourceRow>
      )
    return (
      <SourceRow key={name} tone={s.error ? 'error' : missing.length ? 'warn' : 'ok'} title={label} what={t(`infra.src.${name}`)}>
        {s.error && <span className="text-destructive">{s.error}</span>}
        {missing.length > 0 && (
          <>
            <span className="text-warning">{t('infra.src.missing', { list: missing.join(', ') })}</span>
            <a href={PROVIDER_LINKS[name]} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline pointer-coarse:min-h-10">
              {t('infra.src.fixRights')} <ArrowUpRight className="size-3" />
            </a>
          </>
        )}
      </SourceRow>
    )
  }
  const platform = (id: (typeof PLATFORMS)[number]) => {
    const s = v.sources[id]
    if (!s) return null
    const missing = Object.entries(s.sections || {}).filter(([, x]) => x && x !== 'ok').map(([k]) => tDyn(t, `infra.section.${k}`, k))
    const title = (
      <span className="inline-flex items-center gap-2">
        {s.label || id}
        {s.beta && <Badge variant="muted">{t('infra.beta')}</Badge>}
      </span>
    )
    if (!s.connected)
      return (
        <SourceRow key={id} tone="idle" title={title} what={t(`infra.src.${id}`)} muted>
          {id === 'github' ? (
            <span className="text-muted-foreground">{t('infra.src.githubHow')}</span>
          ) : (
            <>
              {s.token_url && (
                <a href={s.token_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline pointer-coarse:min-h-10">
                  {t('infra.src.createToken')} <ArrowUpRight className="size-3" />
                </a>
              )}
              <Button variant="outline" size="sm" asChild>
                <Link to="/settings/keys">
                  <KeyRound /> {t('infra.src.addKey', { key: s.keys?.[0] || '' })}
                </Link>
              </Button>
            </>
          )}
        </SourceRow>
      )
    return (
      <SourceRow key={id} tone={s.error ? 'error' : missing.length ? 'warn' : 'ok'} title={title} what={t(`infra.src.${id}`)}>
        {s.error && <span className="max-w-80 truncate text-destructive" title={s.error}>{s.error}</span>}
        {missing.length > 0 && <span className="text-warning">{t('infra.src.missing', { list: missing.join(', ') })}</span>}
      </SourceRow>
    )
  }
  const off = PLATFORMS.filter((id) => v.sources[id] && !v.sources[id]!.connected)
  return (
    <section className="grid gap-2" data-testid="infra-sources-panel">
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold">{t('infra.src.title')}</h2>
        <DocLink className="ml-auto" />
      </div>
      <ul className="grid gap-2">
        {servers.map(([name, s]) => (
          <SourceRow key={name} tone={s.ok ? 'ok' : 'error'} title={locationLabel(name, t)} what={name === 'local' ? t('infra.src.local') : t('infra.src.ssh')}>
            {!s.ok && <span className="max-w-80 truncate text-destructive" title={s.error || ''}>{s.error}</span>}
          </SourceRow>
        ))}
        {notRead.length > 0 && (
          <SourceRow tone="warn" title={t('infra.src.notRead', { count: notRead.length })} what={t('infra.src.notReadWhat')}>
            <Button size="sm" onClick={onServers}>
              <Plug /> {t('infra.srv.connect')}
            </Button>
          </SourceRow>
        )}
        {provider('cloudflare', v.sources.cloudflare)}
        {provider('hostinger', v.sources.hostinger)}
        {PLATFORMS.filter((id) => v.sources[id]?.connected).map(platform)}
      </ul>
      {off.length > 0 && (
        <>
          <h3 className="mt-2 text-xs font-medium text-muted-foreground">{t('infra.src.more')}</h3>
          <ul className="grid gap-2">{off.map(platform)}</ul>
        </>
      )}
      <p className="text-xs text-muted-foreground">
        {t('infra.src.notListed')} <DocLink />
      </p>
      {!v.servers.length && !notRead.length && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <ServerCog className="size-3.5" /> {t('infra.src.otherServers')}
        </p>
      )}
    </section>
  )
}

function Meter({ label, used, total }: { label: string; used: number; total: number }) {
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0
  return (
    <div className="grid gap-1">
      <div className="flex justify-between gap-1 text-[11px] text-muted-foreground">
        <span className="truncate">{label}</span>
        <span className="shrink-0 tabular-nums">{pct} %</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full', pct >= 90 ? 'bg-destructive' : pct >= 75 ? 'bg-warning' : 'bg-primary')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Servers tab: one card per server, with its load and what runs on it. */
export function ServerCard({ r, all, onOpen, onConnect }: { r: InfraResource; all: InfraResource[]; onOpen: () => void; onConnect?: React.ReactNode }) {
  const t = useT()
  const d = r.details
  const loc = d.this ? 'local' : d.server
  const here = loc ? all.filter((x) => x.location === loc && x.kind !== 'server') : []
  const count = (k: string) => here.filter((x) => x.kind === k).length
  const how = d.this ? t('infra.src.local') : d.not_connected ? t('infra.srv.notRead') : t('infra.srv.viaSsh', { user: d.user || 'root', host: d.host || '' })
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
        className={cn('grid h-full cursor-pointer content-start gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40', d.not_connected && 'border-dashed')}
        data-testid="infra-server-card"
      >
        <div className="flex items-start gap-3">
          <ServerCog className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="grid min-w-0 flex-1 gap-0.5">
            <span className="flex items-center gap-2">
              <StatusDot tone={r.status === 'ok' ? 'ok' : r.status === 'down' ? 'error' : r.status === 'warn' ? 'warn' : 'idle'} />
              <span className="truncate font-medium">{d.this ? t('infra.thisServer') : r.name}</span>
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {[d.hostname && d.hostname !== r.name ? d.hostname : null, (d.ips || [])[0], d.os || d.hostinger?.os].filter(Boolean).join(' · ')}
            </span>
            <span className="text-xs text-muted-foreground">{how}</span>
          </div>
        </div>
        {d.mem_total ? (
          <div className="grid grid-cols-3 gap-3">
            <Meter label={t('infra.meter.memory')} used={d.mem_total - (d.mem_available || 0)} total={d.mem_total} />
            <Meter label={t('infra.meter.disk')} used={(d.disk_total || 0) - (d.disk_free || 0)} total={d.disk_total || 0} />
            <Meter label={t('infra.meter.cpu', { count: d.cpus || 0 })} used={Math.min(d.load?.[0] || 0, d.cpus || 1)} total={d.cpus || 1} />
          </div>
        ) : null}
        {here.length > 0 && (
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            {(['site', 'database', 'bucket'] as const).map((k) => {
              const n = count(k)
              if (!n) return null
              const Icon = KIND_ICON[k]
              return (
                <span key={k} className="inline-flex items-center gap-1">
                  <Icon className="size-3.5" /> {t(`infra.count.${k}`, { count: n })}
                </span>
              )
            })}
          </div>
        )}
        {onConnect && (
          <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            {onConnect}
          </div>
        )}
      </div>
    </li>
  )
}
