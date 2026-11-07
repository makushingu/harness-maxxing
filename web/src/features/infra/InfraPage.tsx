// Feature page "Infra" (/infra, Settings -> Features -> infra_page): every site, database, bucket, domain and server -
// this server, the other servers read over SSH, Cloudflare, Hostinger - with its status, its links and where it lives.
// Read-only, except connecting / renaming the other servers (ServerConnect); other changes go through the chat ("Ask Claude"). The tab and the open resource are in the URL
// (?tab=sites&id=<resource id>), so a notification or a chat block can point to one.
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AlertTriangle, ArrowUpRight, Cloud, Eye, EyeOff, FolderGit2, HelpCircle, LayoutGrid, Mail, MessageSquarePlus, Network, RefreshCw, Search, Server, ServerCog, Settings2 } from 'lucide-react'
import { useCreateSession, useInfra, useInfraAnnotate, useInfraRefresh, useSettings, useWorkspace } from '@/lib/queries'
import type { InfraKind, InfraResource, InfraView } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtBytes, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { tDyn, useLang, useT, type TFn } from '@/i18n'
import {
  Badge, Button, EmptyState, Input, Select, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle,
  Sensitive, Skeleton, StatusDot, Switch, Textarea, useMask, usePresentation,
} from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { KIND_ICON, STATUS_TONE, locationLabel, providerName, rememberServers, statusText, subtitle } from './shared'
import { MixBar, PlaceIcon, PlaceName, PlaceTag, ResourceRow, TypeView, placeCounts } from './TypeView'
import { placeInfo, placeOf } from './places'
import { AddDomain, AddServer, ConnectVps, RemoveDomain, ServerSettings } from './ServerConnect'
import { HowItWorks, ServerCard, SourcesPanel, useHowItWorks } from './Overview'
import { MailInfra } from './MailInfra'

type Tab = 'overview' | 'problems' | 'sites' | 'databases' | 'buckets' | 'domains' | 'servers' | 'mail'
type KindTab = Exclude<Tab, 'overview' | 'problems' | 'mail'>
const TAB_KINDS: Record<KindTab, InfraKind[]> = {
  sites: ['site', 'worker', 'pages'],
  databases: ['database'],
  buckets: ['bucket'],
  domains: ['domain'],
  servers: ['server'],
}
const TABS = Object.keys(TAB_KINDS) as KindTab[]
const tabOf = (k: InfraKind): KindTab => TABS.find((t) => TAB_KINDS[t].includes(k)) || 'sites'
const ORDER: Record<string, number> = { down: 0, warn: 1, unknown: 2, ok: 3 }

const TYPE_ICON: Record<'sites' | 'databases' | 'buckets' | 'domains', React.ComponentType<{ className?: string }>> = {
  sites: KIND_ICON.site,
  databases: KIND_ICON.database,
  buckets: KIND_ICON.bucket,
  domains: KIND_ICON.domain,
}
const TYPES = ['sites', 'databases', 'buckets', 'domains'] as const
const isProblem = (r: InfraResource) => r.status === 'down' || r.status === 'warn'

/** Inner sidebar of the page (a row of pills on a phone): the overview, what to look at, each type, then the places. */
function InfraNav({ tab, onTab, v, items, byId }: { tab: Tab; onTab: (t: Tab) => void; v: InfraView; items: InfraResource[]; byId: Map<string, InfraResource> }) {
  const t = useT()
  const problems = items.filter(isProblem)
  const down = problems.filter((r) => r.status === 'down').length
  const servers = items.filter((r) => r.kind === 'server')
  const entries: { id: Tab; icon: React.ComponentType<{ className?: string }>; label: string; n?: number; bad?: number; warn?: number; mix?: InfraResource[]; section?: string }[] = [
    { id: 'overview', icon: LayoutGrid, label: t('infra.tab.overview') },
    { id: 'problems', icon: AlertTriangle, label: t('infra.problems'), bad: down, warn: problems.length - down },
    ...TYPES.map((x) => {
      const list = items.filter((r) => TAB_KINDS[x].includes(r.kind))
      const down = list.filter((r) => r.status === 'down').length
      const warn = list.filter((r) => r.status === 'warn').length
      return { id: x as Tab, icon: TYPE_ICON[x], label: t(`infra.tab.${x}`), n: list.length, bad: down, warn, mix: list, section: x === 'sites' ? t('infra.nav.what') : undefined }
    }),
    { id: 'mail', icon: Mail, label: t('infra.mail.tab') },
    { id: 'servers', icon: ServerCog, label: t('infra.nav.places'), n: servers.length, bad: servers.filter((r) => r.status === 'down').length, section: t('infra.nav.where') },
  ]
  const pill = (n: number, cls: string) => <span className={cn('rounded-full px-1.5 text-[11px] leading-4 font-semibold tabular-nums', cls)}>{n}</span>
  return (
    <>
      <nav aria-label={t('infra.title')} className="-mx-4 -mt-5 mb-1 border-b px-3 py-2 md:hidden">
        <ul className="flex gap-1 overflow-x-auto [scrollbar-width:none]">
          {entries.map((e) => (
            <li key={e.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onTab(e.id)}
                className={cn('flex h-10 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium whitespace-nowrap text-muted-foreground', tab === e.id && 'bg-secondary text-foreground')}
              >
                {e.label}
                {!!e.bad && pill(e.bad, 'bg-destructive/15 text-destructive')}
                {e.n != null && <span className="text-xs tabular-nums opacity-70">{e.n}</span>}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <nav aria-label={t('infra.title')} className="sticky top-[calc(var(--header-h)+1.5rem)] hidden w-52 shrink-0 self-start md:block" data-testid="infra-nav">
        <ul className="grid gap-0.5">
          {entries.map((e) => (
            <React.Fragment key={e.id}>
              {e.section && <li className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">{e.section}</li>}
              <li>
                <button
                  type="button"
                  onClick={() => onTab(e.id)}
                  aria-current={tab === e.id ? 'page' : undefined}
                  className={cn(
                    'relative flex w-full flex-col justify-center rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground',
                    e.mix ? 'h-11' : 'h-9',
                    tab === e.id && 'bg-accent font-medium text-foreground hover:bg-accent',
                  )}
                  data-testid={`infra-tab-${e.id}`}
                >
                  <span className="flex w-full items-center gap-2.5">
                    <e.icon className={cn('size-4 shrink-0', tab === e.id && 'text-primary')} />
                    <span className="flex-1 truncate text-left">{e.label}</span>
                    {!!e.bad && pill(e.bad, 'bg-destructive/15 text-destructive')}
                    {!!e.warn && pill(e.warn, 'bg-warning/15 text-warning')}
                    {e.n != null && <span className="min-w-5 text-right text-xs tabular-nums text-muted-foreground">{e.n}</span>}
                  </span>
                  {e.mix && e.mix.length > 0 && (
                    <MixBar parts={placeCounts(e.mix, byId).map(([k, n]) => ({ p: placeInfo(k, v, t), n }))} className="mt-1.5 ml-[26px] h-[3px] w-[calc(100%-26px)]" />
                  )}
                </button>
              </li>
            </React.Fragment>
          ))}
        </ul>
      </nav>
    </>
  )
}

function Problems({ v, items, byId, onOpen, limit }: { v: InfraView; items: InfraResource[]; byId: Map<string, InfraResource>; onOpen: (id: string) => void; limit?: number }) {
  const t = useT()
  const list = items.filter(isProblem).sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.name.localeCompare(b.name))
  if (!list.length) return <p className="rounded-xl border border-dashed px-4 py-3 text-[13px] text-muted-foreground">{t('infra.noProblem')}</p>
  const shown = limit ? list.slice(0, limit) : list
  return (
    <ul className="divide-y overflow-hidden rounded-xl border border-destructive/25 bg-destructive/[0.03]">
      {shown.map((r) => (
        <li key={r.id} className="flex items-center gap-3 pr-3">
          <div className="min-w-0 flex-1">
            <ul>
              <ResourceRow r={r} byId={byId} v={v} onOpen={() => onOpen(r.id)} />
            </ul>
          </div>
          <PlaceTag p={placeInfo(placeOf(r, byId), v, t)} className="max-sm:hidden" />
        </li>
      ))}
    </ul>
  )
}

/** Overview: what to look at, then a table of each type by place (your servers, then hosted elsewhere). */
function Overview({ v, items, all, byId, onOpen, onPlace, onTab, how }: { v: InfraView; items: InfraResource[]; all: InfraResource[]; byId: Map<string, InfraResource>; onOpen: (id: string) => void; onPlace: (tab: Tab, at: string) => void; onTab: (t: Tab) => void; how: ReturnType<typeof useHowItWorks> }) {
  const t = useT()
  const counts = Object.fromEntries(TYPES.map((x) => [x, new Map(placeCounts(items.filter((r) => TAB_KINDS[x].includes(r.kind)), byId))])) as Record<(typeof TYPES)[number], Map<string, number>>
  const keys = [...new Set(TYPES.flatMap((x) => [...counts[x].keys()]))]
  const cols = placeCounts(items.filter((r) => r.kind !== 'server'), byId).map(([k]) => k).filter((k) => keys.includes(k)).map((k) => placeInfo(k, v, t))
  const own = cols.filter((p) => p.tier === 'own')
  const other = cols.filter((p) => p.tier !== 'own')
  const servers = new Map(items.filter((r) => r.kind === 'server').map((r) => [r.location, r]))
  const nProblems = items.filter(isProblem).length
  const mask = useMask()
  const grid = { gridTemplateColumns: `8.5rem repeat(${cols.length}, minmax(5.5rem, 1fr)) 4rem` }
  const meterOf = (k: string) => {
    const d = servers.get(k)?.details
    if (!d?.mem_total) return null
    const mem = Math.round(100 - (100 * d.mem_available) / d.mem_total)
    const disk = d.disk_total ? Math.round(100 - (100 * d.disk_free) / d.disk_total) : null
    return (
      <span className="grid text-[11px] leading-tight whitespace-nowrap text-muted-foreground">
        <span className={cn(mem >= 80 ? 'text-destructive' : mem >= 65 && 'text-warning')}>{t('infra.place.mem', { n: mem })}</span>
        {disk != null && <span className={cn(disk >= 80 ? 'text-destructive' : disk >= 65 && 'text-warning')}>{t('infra.place.disk', { n: disk })}</span>}
      </span>
    )
  }
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      {!how.hidden && <HowItWorks onHide={how.hide} />}
      <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">{t('infra.problems')}</h2>
          {nProblems > 4 && (
            <button type="button" onClick={() => onTab('problems')} className="ml-auto text-xs text-muted-foreground hover:text-foreground pointer-coarse:min-h-10">
              {t('infra.place.seeAll', { count: nProblems })}
            </button>
          )}
        </div>
        <Problems v={v} items={items} byId={byId} onOpen={onOpen} limit={4} />
      </section>
      <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
        <h2 className="text-sm font-semibold">{t('infra.place.matrixTitle')}</h2>
        <div className="overflow-x-auto rounded-xl border bg-card" data-testid="infra-matrix">
          <div className="min-w-fit text-[13px]">
            <div className="grid text-[11px] font-semibold tracking-wider uppercase" style={grid}>
              <span />
              {own.length > 0 && (
                <span className="flex items-center justify-center gap-1.5 bg-primary/8 py-2 text-primary" style={{ gridColumn: `span ${own.length}` }}>
                  <Server className="size-3" /> {t('infra.place.own')}
                </span>
              )}
              {other.length > 0 && (
                <span className="flex items-center justify-center gap-1.5 border-l border-dashed py-2 text-muted-foreground" style={{ gridColumn: `span ${other.length}` }}>
                  <Cloud className="size-3" /> {t('infra.place.hosted')}
                </span>
              )}
              <span />
            </div>
            <div className="grid" style={grid}>
              <span />
              {cols.map((p, i) => (
                <div key={p.key} className={cn('flex flex-col items-center gap-1 px-1.5 pt-2.5 pb-2 text-center', p.tier === 'own' && 'bg-primary/4', p.tier !== 'own' && i === own.length && 'border-l border-dashed')}>
                  <PlaceIcon p={p} />
                  <span className="max-w-full truncate text-xs font-semibold">
                    <PlaceName p={p} />
                  </span>
                  {p.tier === 'own' ? meterOf(p.key) : <span className="text-[11px] text-muted-foreground">{p.tier === 'none' ? t('infra.place.noneShort') : (v.sources as Record<string, { connected?: boolean } | undefined>)[p.key]?.connected ? t('infra.place.apiShort') : t('infra.place.notRead')}</span>}
                </div>
              ))}
              <span className="flex items-end justify-center pb-2 text-xs text-muted-foreground">{t('infra.place.total')}</span>
            </div>
            {TYPES.map((x) => {
              const Icon = TYPE_ICON[x]
              const total = [...counts[x].values()].reduce((a, n) => a + n, 0)
              return (
                <div key={x} className="grid border-t" style={grid}>
                  <button type="button" onClick={() => onTab(x)} className="flex items-center gap-2 px-3.5 text-left font-medium hover:text-primary">
                    <Icon className="size-3.5 text-muted-foreground" /> {t(`infra.tab.${x}`)}
                  </button>
                  {cols.map((p, i) => {
                    const n = counts[x].get(p.key)
                    return (
                      <span key={p.key} className={cn('flex min-h-12 items-center justify-center', p.tier === 'own' && 'bg-primary/4', p.tier !== 'own' && i === own.length && 'border-l border-dashed')}>
                        {n ? (
                          <button
                            type="button"
                            onClick={() => onPlace(x, p.key)}
                            className="min-w-11 rounded-lg px-2.5 py-1 text-base font-semibold tabular-nums transition-colors"
                            style={{ color: `color-mix(in oklch, ${p.color} 80%, var(--foreground))`, background: `color-mix(in oklch, ${p.color} 13%, transparent)` }}
                            title={`${t(`infra.tab.${x}`)} · ${p.sensitive ? mask(p.label) : p.label}`}
                          >
                            {n}
                          </button>
                        ) : (
                          <span className="text-muted-foreground/50">·</span>
                        )}
                      </span>
                    )
                  })}
                  <button type="button" onClick={() => onTab(x)} className="flex items-center justify-center font-semibold text-muted-foreground tabular-nums hover:text-foreground">
                    {total}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{t('infra.place.matrixHint')}</p>
      </section>
      <SourcesPanel v={v} all={all} onServers={() => onTab('servers')} />
    </div>
  )
}

function KV({ k, children }: { k: React.ReactNode; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  )
}

function Details({ r, t, lang }: { r: InfraResource; t: TFn; lang: string }) {
  const d = r.details
  const rows: [React.ReactNode, React.ReactNode][] = []
  const add = (k: React.ReactNode, v: React.ReactNode) => v !== undefined && v !== null && v !== '' && rows.push([k, v])
  if (r.kind === 'site') {
    add(t('infra.d.type'), tDyn(t, `infra.siteKind.${d.kind}`, d.kind))
    add(t('infra.d.target'), (d.upstreams || []).join(', ') || d.root || d.redirect)
    for (const s of d.services || [])
      add(
        t('infra.d.service'),
        <span className="font-mono text-xs">
          :{s.port} {s.unit || (s.container ? `docker ${s.container}` : s.process)}
          {s.cwd && <span className="block text-muted-foreground">{s.cwd}</span>}
        </span>,
      )
    if (d.cert?.expires) add(t('infra.d.cert'), t('infra.certLeft', { count: d.cert.days_left, issuer: d.cert.issuer || '' }))
    if (d.dns?.length) add('DNS', d.dns.map((x: { type: string; content: string }) => `${x.type} ${x.content}`).join(', '))
  }
  if (r.kind === 'database' || r.kind === 'bucket') {
    add(t('infra.d.engine'), d.engine)
    add(t('infra.d.size'), d.size != null ? fmtBytes(d.size) : d.bytes != null ? fmtBytes(d.bytes) : null)
    add(t('infra.d.owner'), d.owner)
    add(t('infra.d.container'), d.container)
    add(t('infra.d.port'), d.port)
    add(t('infra.d.path'), d.path && <span className="font-mono text-xs">{d.path}</span>)
    add(t('infra.d.endpoint'), d.s3_endpoint)
    if (d.backup) add(t('infra.d.backup'), d.backup.ok ? fmtRelative(d.backup.at, lang) : <span className="text-destructive">{d.backup.error}</span>)
  }
  if (r.kind === 'domain') {
    add(t('infra.d.registrar'), providerName(d.registrar, t))
    add(t('infra.d.expires'), d.expires ? `${new Date(d.expires * 1000).toLocaleDateString(lang)}${d.auto_renew ? ` · ${t('infra.autoRenew')}` : ''}` : null)
    add('DNS', providerName(d.dns, t))
    add(t('infra.d.ns'), (d.name_servers || []).join(', '))
    add(t('infra.d.hostedBy'), providerName(d.hosted_by, t))
    if (d.unused_zone) add(t('infra.d.unusedZone'), <span className="text-muted-foreground">{t('infra.unusedZone', { name: providerName(d.unused_zone, t) })}</span>)
    if (d.www_hosted_by && d.www_hosted_by !== d.hosted_by) add(<>www.<Sensitive>{r.name}</Sensitive></>, providerName(d.www_hosted_by, t))
    if (d.dns_error) add('DNS', <span className="text-warning">{tDyn(t, `infra.why.${d.dns_error}`, d.dns_error)}</span>)
    if (d.records?.length)
      add(
        t('infra.d.records'),
        <span className="grid gap-0.5 font-mono text-[11px]">
          {d.records.slice(0, 40).map((x: { type: string; name: string; content: string }, i: number) => (
            <span key={i}>
              {x.type} {x.name} → {x.content}
            </span>
          ))}
        </span>,
      )
  }
  if (r.kind === 'server') {
    add(t('infra.d.host'), d.host || d.hostname)
    add('IP', (d.ips || []).join(', '))
    add(t('infra.d.os'), d.os)
    add('CPU', d.cpus)
    add(t('infra.d.memory'), d.mem_total ? `${fmtBytes(d.mem_available)} / ${fmtBytes(d.mem_total)}` : null)
    add(t('infra.d.disk'), d.disk_total ? `${fmtBytes(d.disk_free)} / ${fmtBytes(d.disk_total)}` : null)
    add(t('infra.d.load'), d.load?.join(' '))
    add(t('infra.d.web'), (d.web_servers || []).join(', '))
    if (d.hostinger) add('Hostinger', `${d.hostinger.plan || ''} · ${d.hostinger.state || ''}`)
    if (d.not_connected) add('SSH', <span className="text-warning">{t('infra.notConnected')}</span>)
  }
  if (r.kind === 'worker') add(t('infra.d.routes'), (d.routes || []).join(', '))
  if (r.kind === 'pages') {
    add(t('infra.d.deployed'), d.deployed ? fmtRelative(d.deployed, lang) : null)
    add(t('infra.d.framework'), d.framework)
    add(t('infra.d.team'), d.team)
  }
  if (d.platform && r.kind === 'database') add(t('infra.d.region'), d.region)
  if (!rows.length) return null
  return (
    <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
      {rows.map(([k, v], i) => (
        <KV key={i} k={k}>
          <Sensitive length={12}>{v}</Sensitive>
        </KV>
      ))}
    </dl>
  )
}

function AskClaude({ r }: { r: InfraResource }) {
  const mask = useMask()
  const t = useT()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const create = useCreateSession()
  const [q, setQ] = React.useState('')
  const topics = (ws?.projects || []).flatMap((p) => p.topics.map((tp) => ({ project: p.name, path: tp.path, label: `${p.name}/${tp.name}` })))
  const fallback = topics.find((tp) => tp.path.endsWith('/topics/inbox'))?.path || topics[0]?.path || ''
  const [topic, setTopic] = React.useState(() => topics.find((tp) => tp.project === r.project)?.path || fallback)
  React.useEffect(() => {
    if (!topic && fallback) setTopic(topics.find((tp) => tp.project === r.project)?.path || fallback)
  }, [topic, fallback, topics, r.project])
  const send = () => {
    const ctx = [
      `Infra resource \`${r.id}\` (${r.kind} "${r.name}", ${locationLabel(r.location, t)}${r.urls[0] ? `, ${r.urls[0]}` : ''}).`,
      `Status: ${r.status}${r.status_detail ? ` (${r.status_detail})` : ''}. Details: \`maxxing infra list --json\` (skill maxxing-infra).`,
      '',
      q.trim(),
    ].join('\n')
    create.mutate({ path: topic, title: `${r.name}`.slice(0, 60), message: ctx }, { onSuccess: (s) => navigate(`/sessions/${s.id}`) })
  }
  return (
    <div className="grid gap-2 rounded-xl border bg-card p-3">
      <p className="flex items-center gap-2 text-sm font-medium">
        <MessageSquarePlus className="size-4" /> {t('infra.ask')}
      </p>
      <Textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('infra.askPlaceholder')} rows={3} />
      <div className="flex flex-wrap items-center gap-2">
        <Select value={topic || undefined} onValueChange={setTopic} options={topics.map((tp) => ({ value: tp.path, label: mask(tp.label) }))} className="h-8 w-auto max-w-56 text-xs" aria-label={t('infra.askTopic')} />
        <Button size="sm" className="ml-auto" disabled={!q.trim() || !topic} loading={create.isPending} onClick={send}>
          {t('infra.askSend')}
        </Button>
      </div>
      {create.error && <p className="text-xs text-destructive">{errorMessage(create.error)}</p>}
    </div>
  )
}

function Detail({ r, v, byId, onOpen, projects }: { r: InfraResource; v: InfraView; byId: Map<string, InfraResource>; onOpen: (id: string) => void; projects: string[] }) {
  const t = useT()
  const hide = usePresentation()
  const mask = useMask()
  const lang = useLang()
  const annotate = useInfraAnnotate()
  const [note, setNote] = React.useState(r.note)
  React.useEffect(() => setNote(r.note), [r.id, r.note])
  const d = r.details
  const repos = [d.repo, ...(d.services || []).map((s: { repo?: unknown }) => s.repo)].filter(Boolean) as { git: string | null; github: string | null; path?: string }[]
  const dashboard = d.dashboard || d.hostinger_dashboard
  const links = r.links.map((id) => byId.get(id)).filter(Boolean) as InfraResource[]
  const Icon = KIND_ICON[r.kind]
  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2 pr-8">
          <Icon className="size-4 shrink-0 text-primary" />
          <span className="truncate">
            <Sensitive length={14}>{r.name}</Sensitive>
          </span>
        </SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-2">
          <StatusDot tone={STATUS_TONE[r.status]} />
          <span>{statusText(r, t)}</span>
          <span>·</span>
          <span>
            <PlaceName p={placeInfo(r.location, v, t)} />
          </span>
          <span>·</span>
          <span>{tDyn(t, `infra.kind.${r.kind}`, r.kind)}</span>
          {r.declared && <Badge variant="muted">{t('infra.declared')}</Badge>}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="grid content-start gap-4">
        {r.missing && <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-2.5 text-[13px]">{t('infra.missingHint')}</p>}
        {r.urls.length > 0 && !hide && (
          <div className="grid gap-1">
            {r.urls.map((u) => {
              const c = (d.checks || []).find((x: { url: string }) => x.url === u)
              return (
                <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline pointer-coarse:min-h-10">
                  {c && <StatusDot tone={STATUS_TONE[c.status as 'ok']} />}
                  {u} <ArrowUpRight className="size-3.5" />
                  {c?.code && <span className="text-xs text-muted-foreground">{c.code} · {c.ms} ms</span>}
                </a>
              )
            })}
          </div>
        )}
        <Details r={r} t={t} lang={lang} />
        {r.kind === 'server' && d.not_connected && <ConnectVps r={r} />}
        {r.kind === 'domain' && d.added && <RemoveDomain name={r.name} />}
        {r.kind === 'server' && d.server && r.location !== 'local' && <ServerSettings r={r} />}
        <div className="flex flex-wrap gap-2">
          {repos.map((rp, i) =>
            rp.git ? (
              <Button key={i} variant="outline" size="sm" asChild>
                <Link to={`/git?repo=${encodeURIComponent(rp.git)}`}>
                  <FolderGit2 /> {mask(rp.github || rp.path?.split('/').pop() || '')}
                </Link>
              </Button>
            ) : null,
          )}
          {dashboard && (
            <Button variant="outline" size="sm" asChild>
              <a href={dashboard} target="_blank" rel="noopener noreferrer">
                {d.platform ? providerName(d.platform, t) : d.hostinger_dashboard && !d.dashboard ? 'Hostinger' : 'Cloudflare'} <ArrowUpRight />
              </a>
            </Button>
          )}
        </div>
        {links.length > 0 && (
          <div className="grid gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">{t('infra.linked')}</p>
            <ul className="grid gap-1">
              {links.map((l) => {
                const LIcon = KIND_ICON[l.kind]
                return (
                  <li key={l.id}>
                    <button type="button" onClick={() => onOpen(l.id)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-accent/60">
                      <StatusDot tone={STATUS_TONE[l.status]} />
                      <LIcon className="size-3.5 text-muted-foreground" />
                      <span className="truncate">
                        <Sensitive length={12}>{l.name}</Sensitive>
                      </span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        <PlaceName p={placeInfo(l.location, v, t)} />
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
        <div className="grid gap-2 rounded-xl border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">{t('infra.project')}</span>
            <Select
              value={r.project || '_none'}
              onValueChange={(v) => annotate.mutate({ id: r.id, project: v === '_none' ? '' : v })}
              options={[{ value: '_none', label: t('infra.noProject') }, ...projects.map((p) => ({ value: p, label: mask(p) }))]}
              className="h-8 w-auto min-w-36 text-xs pointer-coarse:h-10"
              aria-label={t('infra.project')}
            />
            <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
              {t('infra.hide')}
              <Switch checked={r.hidden} onCheckedChange={(v) => annotate.mutate({ id: r.id, hidden: v })} />
            </label>
          </div>
          <Input
            value={hide ? mask(note) : note}
            readOnly={hide}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== r.note && annotate.mutate({ id: r.id, note })}
            placeholder={t('infra.notePlaceholder')}
            className="h-8 text-xs"
          />
        </div>
        <AskClaude key={r.id} r={r} />
        <p className="font-mono text-[11px] break-all text-muted-foreground">
          <Sensitive length={20}>{r.id}</Sensitive>
        </p>
      </SheetBody>
    </>
  )
}

export default function InfraPage() {
  const t = useT()
  const lang = useLang()
  const mask = useMask()
  const { data: settings } = useSettings()
  const on = !!settings?.infra_page
  const { data: v, isLoading, error } = useInfra(on)
  const refresh = useInfraRefresh()
  const { data: ws } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const openId = params.get('id')
  const asked = params.get('tab') as Tab | null
  const tab: Tab = (asked && ([...TABS, 'overview', 'problems', 'mail'] as string[]).includes(asked) ? asked : null) || (openId ? tabOf((v?.resources.find((r) => r.id === openId)?.kind || 'site') as InfraKind) : 'overview')
  const [q, setQ] = React.useState('')
  const [project, setProject] = React.useState('_all')
  const [showHidden, setShowHidden] = React.useState(false)
  const set = (next: { tab?: Tab; id?: string | null; at?: string | null }) => {
    const p = new URLSearchParams(params)
    if (next.tab) p.set('tab', next.tab)
    if (next.at === null) p.delete('at')
    else if (next.at) p.set('at', next.at)
    if (next.id === null) p.delete('id')
    else if (next.id) p.set('id', next.id)
    setParams(p)
  }
  const autoStarted = React.useRef(false)
  React.useEffect(() => {
    if (on && v && !v.generated_at && !v.refreshing && !autoStarted.current) {
      autoStarted.current = true
      refresh.mutate()
    }
  }, [on, v, refresh])

  rememberServers(v?.servers)
  const how = useHowItWorks()
  const all = v?.resources || []
  const byId = React.useMemo(() => new Map(all.map((r) => [r.id, r])), [all])
  const projects = [...new Set([...(ws?.projects || []).map((p) => p.name), ...all.map((r) => r.project).filter(Boolean)])].sort() as string[]
  const needle = q.trim().toLowerCase()
  const visible = all.filter(
    (r) =>
      (showHidden || (!r.hidden && !r.details.system)) &&
      (project === '_all' || r.project === project) &&
      (!needle || `${r.name} ${r.urls.join(' ')} ${r.location} ${r.project || ''} ${r.note} ${subtitle(r, t)}`.toLowerCase().includes(needle)),
  )
  const open = openId ? byId.get(openId) : undefined
  const kindTab = (TABS as string[]).includes(tab) ? (tab as KindTab) : null
  const tabItems = kindTab ? visible.filter((r) => TAB_KINDS[kindTab].includes(r.kind)) : []

  if (settings && !on)
    return (
      <Page title={t('infra.title')} description={t('infra.desc')}>
        <EmptyState
          icon={Network}
          title={t('infra.off')}
          description={t('infra.offDesc')}
          action={
            <Button asChild>
              <Link to="/settings/features">
                <Settings2 /> {t('infra.turnOn')}
              </Link>
            </Button>
          }
        />
      </Page>
    )

  return (
    <Page
      title={t('infra.title')}
      description={t('infra.desc')}
      width="wide"
      actions={
        <>
          <AddServer />
          <Button variant="outline" size="sm" loading={refresh.isPending || !!v?.refreshing} onClick={() => refresh.mutate()} data-testid="infra-refresh">
            <RefreshCw /> <span className="max-[429px]:sr-only">{v?.refreshing ? t('infra.refreshing') : t('infra.refresh')}</span>
          </Button>
        </>
      }
    >
      {isLoading ? (
        <div className="grid gap-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <p className="text-sm text-destructive">{errorMessage(error)}</p>
      ) : v && !v.generated_at ? (
        <EmptyState icon={Network} title={t('infra.firstRun')} description={t('infra.firstRunDesc')} />
      ) : v ? (
        <div className="flex min-w-0 gap-8 max-md:flex-col max-md:gap-3">
          <InfraNav tab={tab} onTab={(x) => set({ tab: x, id: null, at: null })} v={v} items={visible} byId={byId} />
          <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <h2 className="text-lg font-semibold tracking-tight">
                {tab === 'servers' ? t('infra.nav.places') : tab === 'problems' ? t('infra.problems') : tab === 'mail' ? t('infra.mail.tab') : t(`infra.tab.${tab}`)}
                {kindTab && <span className="ml-1.5 font-normal text-muted-foreground tabular-nums">· {tabItems.length}</span>}
              </h2>
              <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                {how.hidden && tab === 'overview' && (
                  <button type="button" onClick={how.show} className="inline-flex items-center gap-1 hover:text-foreground">
                    <HelpCircle className="size-3.5" /> {t('infra.how.title')}
                  </button>
                )}
                <span className="max-md:hidden" title={v.took_ms ? `${(v.took_ms / 1000).toFixed(1)} s` : ''}>
                  {t('infra.updated', { when: fmtRelative(v.generated_at!, lang) })} · {t('infra.every', { count: v.refresh_min || 15 })}
                </span>
              </span>
            </div>
            {v.error && (
              <p className="flex items-center gap-2 text-[13px] text-destructive">
                <AlertTriangle className="size-4" /> <Sensitive length={20}>{v.error}</Sensitive>
              </p>
            )}
            {tab !== 'mail' && (
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-0 flex-1 sm:max-w-72">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('infra.search')} className="pl-8" />
                </div>
                <Select
                  value={project}
                  onValueChange={setProject}
                  options={[{ value: '_all', label: t('infra.allProjects') }, ...projects.map((p) => ({ value: p, label: mask(p) }))]}
                  className="h-9 w-auto min-w-36"
                  aria-label={t('infra.project')}
                />
                <Button variant="ghost" size="icon" onClick={() => setShowHidden((x) => !x)} aria-pressed={showHidden} aria-label={t('infra.showHidden')} title={t('infra.showHidden')}>
                  {showHidden ? <Eye /> : <EyeOff />}
                </Button>
                {tab === 'domains' && <AddDomain />}
              </div>
            )}
            {tab === 'overview' ? (
              <Overview v={v} items={visible} all={all} byId={byId} onOpen={(id) => set({ id })} onPlace={(x, at) => set({ tab: x, at })} onTab={(x) => set({ tab: x, at: null })} how={how} />
            ) : tab === 'mail' ? (
              <MailInfra />
            ) : tab === 'problems' ? (
              <Problems v={v} items={visible} byId={byId} onOpen={(id) => set({ id })} />
            ) : !tabItems.length ? (
              <EmptyState
                icon={KIND_ICON[TAB_KINDS[tab as KindTab][0]]}
                title={t('infra.empty')}
                description={tDyn(t, `infra.emptyHint.${tab}`, '')}
                action={tab === 'domains' ? <AddDomain /> : undefined}
                compact
              />
            ) : tab === 'servers' ? (
              <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
                <p className="text-[13px] text-muted-foreground">{t('infra.srv.tabHint')}</p>
                <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
                  {tabItems
                    .slice()
                    .sort((a, b) => Number(!!b.details.this) - Number(!!a.details.this) || Number(!!a.details.not_connected) - Number(!!b.details.not_connected) || a.name.localeCompare(b.name))
                    .map((r) => (
                      <ServerCard key={r.id} r={r} all={all} onOpen={() => set({ id: r.id })} onConnect={r.details.not_connected ? <ConnectVps r={r} compact /> : undefined} />
                    ))}
                </ul>
                <SourcesPanel v={v} all={all} onServers={() => set({ tab: 'servers' })} />
              </div>
            ) : (
              <TypeView
                items={tabItems}
                v={v}
                byId={byId}
                at={params.get('at')}
                onAt={(at) => set({ at })}
                onOpen={(id) => set({ id })}
                intro={tab === 'domains' ? <p className="text-[13px] text-muted-foreground">{t('infra.dom.tabHint')}</p> : undefined}
              />
            )}
          </div>
        </div>
      ) : null}
      <Sheet open={!!open} onOpenChange={(o) => !o && set({ id: null })}>
        <SheetContent className="w-full sm:max-w-lg">{open && <Detail r={open} v={v!} byId={byId} onOpen={(id) => set({ id, tab: tabOf(byId.get(id)!.kind) })} projects={projects} />}</SheetContent>
      </Sheet>
    </Page>
  )
}
