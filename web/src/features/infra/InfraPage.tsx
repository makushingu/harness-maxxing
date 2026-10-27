// Feature page "Infra" (/infra, Settings -> Features -> infra_page): every site, database, bucket, domain and server -
// this server, the other servers read over SSH, Cloudflare, Hostinger - with its status, its links and where it lives.
// Read-only, except connecting / renaming the other servers (ServerConnect); other changes go through the chat ("Ask Claude"). The tab and the open resource are in the URL
// (?tab=sites&id=<resource id>), so a notification or a chat block can point to one.
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AlertTriangle, ArrowUpRight, Eye, EyeOff, FolderGit2, HelpCircle, KeyRound, MessageSquarePlus, Network, RefreshCw, Search, Settings2 } from 'lucide-react'
import { useCreateSession, useInfra, useInfraAnnotate, useInfraRefresh, useSettings, useWorkspace } from '@/lib/queries'
import type { InfraKind, InfraResource, InfraSource, InfraView } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtBytes, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { tDyn, useLang, useT, type TFn } from '@/i18n'
import {
  Badge, Button, EmptyState, Input, Segmented, Select, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle,
  Skeleton, StatusDot, Switch, Textarea,
} from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { KIND_ICON, LOCATION_ICON, PLATFORMS, STATUS_TONE, locationLabel, providerName, rememberServers, statusText, subtitle } from './shared'
import { AddDomain, AddServer, ConnectVps, RemoveDomain, ServerSettings } from './ServerConnect'
import { HowItWorks, ServerCard, SourcesPanel, useHowItWorks } from './Overview'

type Tab = 'overview' | 'sites' | 'databases' | 'buckets' | 'domains' | 'servers'
const TAB_KINDS: Record<Exclude<Tab, 'overview'>, InfraKind[]> = {
  sites: ['site', 'worker', 'pages'],
  databases: ['database'],
  buckets: ['bucket'],
  domains: ['domain'],
  servers: ['server'],
}
const TABS = Object.keys(TAB_KINDS) as Exclude<Tab, 'overview'>[]
const tabOf = (k: InfraKind): Exclude<Tab, 'overview'> => TABS.find((t) => TAB_KINDS[t].includes(k)) || 'sites'
const ORDER: Record<string, number> = { down: 0, warn: 1, unknown: 2, ok: 3 }

/** Location groups: this server first, then the other servers, then the providers. */
function groupByLocation(items: InfraResource[]) {
  const groups = new Map<string, InfraResource[]>()
  for (const r of items) groups.set(r.location, [...(groups.get(r.location) || []), r])
  const rank = (l: string) =>
    l === 'local' ? 0 : l === 'cloudflare' || (PLATFORMS as readonly string[]).includes(l) ? 2 : l === 'hostinger' ? 3 : l === 'other' ? 4 : 1
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))
}

function Row({ r, onOpen }: { r: InfraResource; onOpen: () => void }) {
  const t = useT()
  const Icon = KIND_ICON[r.kind]
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
        className={cn('flex h-full cursor-pointer items-start gap-3 rounded-xl border bg-card p-3 transition-colors hover:border-primary/40 hover:bg-accent/40', r.hidden && 'opacity-60')}
        data-testid="infra-row"
      >
        <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="grid grid-cols-[minmax(0,1fr)] min-w-0 flex-1 gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <StatusDot tone={STATUS_TONE[r.status]} label={statusText(r, t)} />
            <span className="truncate font-medium">{r.name}</span>
            {r.kind !== 'site' && r.kind !== 'database' && r.kind !== 'bucket' && r.kind !== 'domain' && r.kind !== 'server' && (
              <Badge variant="muted">{tDyn(t, `infra.kind.${r.kind}`, r.kind)}</Badge>
            )}
            {r.details.harness && <Badge variant="muted">Harness</Badge>}
            {r.details.sandbox && <Badge variant="muted">{t('infra.sandboxed')}</Badge>}
            {r.details.system && <Badge variant="muted">{t('infra.system')}</Badge>}
            {r.project && <Badge variant="outline">{r.project}</Badge>}
            {r.status !== 'ok' && r.status !== 'unknown' && (
              <span className={cn('text-xs', r.status === 'down' ? 'text-destructive' : 'text-warning')}>{statusText(r, t)}</span>
            )}
          </div>
          <span className="truncate text-xs text-muted-foreground">{subtitle(r, t)}</span>
          {r.urls.length > 0 && (
            <span className="flex flex-wrap gap-x-3 text-xs">
              {r.urls.slice(0, 3).map((u) => (
                <a key={u} href={u} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="inline-flex min-w-0 max-w-full items-center justify-center gap-0.5 truncate text-primary hover:underline pointer-coarse:min-h-10 pointer-coarse:min-w-10">
                  {u.replace(/^https?:\/\//, '').replace(/\/$/, '')} <ArrowUpRight className="size-3" />
                </a>
              ))}
            </span>
          )}
          {r.note && <span className="truncate text-xs italic text-muted-foreground">{r.note}</span>}
        </div>
      </div>
    </li>
  )
}

function Sources({ v }: { v: InfraView }) {
  const t = useT()
  const servers = Object.entries(v.sources.servers || {})
  const prov = (name: 'cloudflare' | 'hostinger', s?: InfraSource) => {
    if (!s?.connected)
      return (
        <Link key={name} to="/settings/keys" className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-accent pointer-coarse:min-h-10">
          <KeyRound className="size-3" /> {t('infra.connect', { name: locationLabel(name, t) })}
        </Link>
      )
    const missing = Object.entries(s.sections || {}).filter(([, x]) => x && x !== 'ok')
    return (
      <span key={name} className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs', (missing.length || s.error) && 'border-warning/40')} title={s.key || ''}>
        <StatusDot tone={s.error ? 'error' : missing.length ? 'warn' : 'ok'} />
        {locationLabel(name, t)}
        {s.error && <span className="text-destructive">{s.error}</span>}
        {missing.length > 0 && (
          <span className="text-muted-foreground">
            {t('infra.missingRights', { list: missing.map(([k]) => tDyn(t, `infra.section.${k}`, k)).join(', ') })}
          </span>
        )}
      </span>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="infra-sources">
      {servers.map(([name, s]) => (
        <span key={name} className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs', !s.ok && 'border-destructive/40')} title={s.error || ''}>
          <StatusDot tone={s.ok ? 'ok' : 'error'} />
          {locationLabel(name, t)}
          {!s.ok && <span className="max-w-60 truncate text-destructive">{s.error}</span>}
        </span>
      ))}
      {prov('cloudflare', v.sources.cloudflare)}
      {prov('hostinger', v.sources.hostinger)}
    </div>
  )
}

function Overview({ v, items, all, onOpen, onTab, how }: { v: InfraView; items: InfraResource[]; all: InfraResource[]; onOpen: (id: string) => void; onTab: (t: Tab) => void; how: ReturnType<typeof useHowItWorks> }) {
  const t = useT()
  const problems = items.filter((r) => r.status === 'down' || r.status === 'warn').sort((a, b) => ORDER[a.status] - ORDER[b.status])
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      {!how.hidden && <HowItWorks onHide={how.hide} />}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {TABS.map((tab) => {
          const list = items.filter((r) => TAB_KINDS[tab].includes(r.kind))
          const bad = list.filter((r) => r.status === 'down').length
          const warn = list.filter((r) => r.status === 'warn').length
          const Icon = KIND_ICON[TAB_KINDS[tab][0]]
          return (
            <button key={tab} type="button" onClick={() => onTab(tab)} className="grid gap-1 rounded-xl border bg-card p-3 text-left transition-colors hover:border-primary/40" data-testid={`infra-card-${tab}`}>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Icon className="size-3.5" /> {t(`infra.tab.${tab}`)}
              </span>
              <span className="text-2xl font-semibold tabular-nums">{list.length}</span>
              <span className="flex gap-2 text-xs">
                {bad > 0 && <span className="text-destructive">{t('infra.nDown', { count: bad })}</span>}
                {warn > 0 && <span className="text-warning">{t('infra.nWarn', { count: warn })}</span>}
                {!bad && !warn && <span className="text-muted-foreground">{t('infra.allGood')}</span>}
              </span>
            </button>
          )
        })}
      </div>
      <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
        <h2 className="text-sm font-semibold">{t('infra.problems')}</h2>
        {problems.length ? (
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 lg:grid-cols-2">
            {problems.map((r) => (
              <Row key={r.id} r={r} onOpen={() => onOpen(r.id)} />
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted-foreground">{t('infra.noProblem')}</p>
        )}
      </section>
      <SourcesPanel v={v} all={all} onServers={() => onTab('servers')} />
    </div>
  )
}

function KV({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  )
}

function Details({ r, t, lang }: { r: InfraResource; t: TFn; lang: string }) {
  const d = r.details
  const rows: [string, React.ReactNode][] = []
  const add = (k: string, v: React.ReactNode) => v !== undefined && v !== null && v !== '' && rows.push([k, v])
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
    if (d.www_hosted_by && d.www_hosted_by !== d.hosted_by) add(`www.${r.name}`, providerName(d.www_hosted_by, t))
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
          {v}
        </KV>
      ))}
    </dl>
  )
}

function AskClaude({ r }: { r: InfraResource }) {
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
        <Select value={topic || undefined} onValueChange={setTopic} options={topics.map((tp) => ({ value: tp.path, label: tp.label }))} className="h-8 w-auto max-w-56 text-xs" aria-label={t('infra.askTopic')} />
        <Button size="sm" className="ml-auto" disabled={!q.trim() || !topic} loading={create.isPending} onClick={send}>
          {t('infra.askSend')}
        </Button>
      </div>
      {create.error && <p className="text-xs text-destructive">{errorMessage(create.error)}</p>}
    </div>
  )
}

function Detail({ r, byId, onOpen, projects }: { r: InfraResource; byId: Map<string, InfraResource>; onOpen: (id: string) => void; projects: string[] }) {
  const t = useT()
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
          <span className="truncate">{r.name}</span>
        </SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-2">
          <StatusDot tone={STATUS_TONE[r.status]} />
          <span>{statusText(r, t)}</span>
          <span>·</span>
          <span>{locationLabel(r.location, t)}</span>
          <span>·</span>
          <span>{tDyn(t, `infra.kind.${r.kind}`, r.kind)}</span>
          {r.declared && <Badge variant="muted">{t('infra.declared')}</Badge>}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="grid content-start gap-4">
        {r.missing && <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-2.5 text-[13px]">{t('infra.missingHint')}</p>}
        {r.urls.length > 0 && (
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
                  <FolderGit2 /> {rp.github || rp.path?.split('/').pop()}
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
                      <span className="truncate">{l.name}</span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">{locationLabel(l.location, t)}</span>
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
              options={[{ value: '_none', label: t('infra.noProject') }, ...projects.map((p) => ({ value: p, label: p }))]}
              className="h-8 w-auto min-w-36 text-xs pointer-coarse:h-10"
              aria-label={t('infra.project')}
            />
            <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
              {t('infra.hide')}
              <Switch checked={r.hidden} onCheckedChange={(v) => annotate.mutate({ id: r.id, hidden: v })} />
            </label>
          </div>
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== r.note && annotate.mutate({ id: r.id, note })}
            placeholder={t('infra.notePlaceholder')}
            className="h-8 text-xs"
          />
        </div>
        <AskClaude key={r.id} r={r} />
        <p className="font-mono text-[11px] break-all text-muted-foreground">{r.id}</p>
      </SheetBody>
    </>
  )
}

export default function InfraPage() {
  const t = useT()
  const lang = useLang()
  const { data: settings } = useSettings()
  const on = !!settings?.infra_page
  const { data: v, isLoading, error } = useInfra(on)
  const refresh = useInfraRefresh()
  const { data: ws } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const openId = params.get('id')
  const tab = (params.get('tab') as Tab) || (openId ? tabOf((v?.resources.find((r) => r.id === openId)?.kind || 'site') as InfraKind) : 'overview')
  const [q, setQ] = React.useState('')
  const [project, setProject] = React.useState('_all')
  const [showHidden, setShowHidden] = React.useState(false)
  const set = (next: { tab?: Tab; id?: string | null }) => {
    const p = new URLSearchParams(params)
    if (next.tab) p.set('tab', next.tab)
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
      actions={
        <>
          <AddServer />
          <Button variant="outline" size="sm" loading={refresh.isPending || !!v?.refreshing} onClick={() => refresh.mutate()} data-testid="infra-refresh">
            <RefreshCw /> {v?.refreshing ? t('infra.refreshing') : t('infra.refresh')}
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
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {tab !== 'overview' && <Sources v={v} />}
            <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
              {how.hidden && tab === 'overview' && (
                <button type="button" onClick={how.show} className="inline-flex items-center gap-1 hover:text-foreground">
                  <HelpCircle className="size-3.5" /> {t('infra.how.title')}
                </button>
              )}
              <span title={v.took_ms ? `${(v.took_ms / 1000).toFixed(1)} s` : ''}>
                {t('infra.updated', { when: fmtRelative(v.generated_at!, lang) })} · {t('infra.every', { count: v.refresh_min || 15 })}
              </span>
            </span>
          </div>
          {v.error && (
            <p className="flex items-center gap-2 text-[13px] text-destructive">
              <AlertTriangle className="size-4" /> {v.error}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <div className="max-w-full min-w-0 overflow-x-auto">
              <Segmented
                value={tab}
                onChange={(x) => set({ tab: x, id: null })}
                aria-label={t('infra.title')}
                options={[
                  { value: 'overview', label: t('infra.tab.overview') },
                  ...TABS.map((x) => ({ value: x, label: `${t(`infra.tab.${x}`)} · ${visible.filter((r) => TAB_KINDS[x].includes(r.kind)).length}` })),
                ]}
              />
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Select
                value={project}
                onValueChange={setProject}
                options={[{ value: '_all', label: t('infra.allProjects') }, ...projects.map((p) => ({ value: p, label: p }))]}
                className="h-9 w-auto min-w-36"
                aria-label={t('infra.project')}
              />
              <div className="relative w-full sm:w-56">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('infra.search')} className="pl-8" />
              </div>
              <Button variant="ghost" size="icon" onClick={() => setShowHidden((x) => !x)} aria-pressed={showHidden} aria-label={t('infra.showHidden')} title={t('infra.showHidden')}>
                {showHidden ? <Eye /> : <EyeOff />}
              </Button>
            </div>
          </div>
          {tab === 'overview' ? (
            <Overview v={v} items={visible} all={all} onOpen={(id) => set({ id })} onTab={(x) => set({ tab: x })} how={how} />
          ) : (
            (() => {
              const items = visible.filter((r) => TAB_KINDS[tab].includes(r.kind))
              if (!items.length)
                return (
                  <EmptyState
                    icon={KIND_ICON[TAB_KINDS[tab][0]]}
                    title={t('infra.empty')}
                    description={tDyn(t, `infra.emptyHint.${tab}`, '')}
                    action={tab === 'domains' ? <AddDomain /> : undefined}
                    compact
                  />
                )
              if (tab === 'servers')
                return (
                  <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
                    <p className="text-[13px] text-muted-foreground">{t('infra.srv.tabHint')}</p>
                    <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2">
                      {items
                        .slice()
                        .sort((a, b) => Number(!!b.details.this) - Number(!!a.details.this) || Number(!!a.details.not_connected) - Number(!!b.details.not_connected) || a.name.localeCompare(b.name))
                        .map((r) => (
                          <ServerCard key={r.id} r={r} all={all} onOpen={() => set({ id: r.id })} onConnect={r.details.not_connected ? <ConnectVps r={r} compact /> : undefined} />
                        ))}
                    </ul>
                  </div>
                )
              return (
                <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
                  {tab === 'domains' && (
                    <div className="flex flex-wrap items-center gap-3">
                      <p className="min-w-0 flex-1 text-[13px] text-muted-foreground">{t('infra.dom.tabHint')}</p>
                      <AddDomain />
                    </div>
                  )}
                  {groupByLocation(items).map(([loc, list]) => {
                    const LIcon = LOCATION_ICON(loc)
                    return (
                      <section key={loc} className="grid grid-cols-[minmax(0,1fr)] gap-2">
                        <h2 className="flex items-center gap-2 text-sm font-semibold">
                          <LIcon className="size-4 text-muted-foreground" /> {locationLabel(loc, t)}
                          <span className="text-xs font-normal text-muted-foreground">{list.length}</span>
                        </h2>
                        <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 lg:grid-cols-2">
                          {list
                            .slice()
                            .sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.name.localeCompare(b.name))
                            .map((r) => (
                              <Row key={r.id} r={r} onOpen={() => set({ id: r.id })} />
                            ))}
                        </ul>
                      </section>
                    )
                  })}
                </div>
              )
            })()
          )}
        </div>
      ) : null}
      <Sheet open={!!open} onOpenChange={(o) => !o && set({ id: null })}>
        <SheetContent className="w-full sm:max-w-lg">{open && <Detail r={open} byId={byId} onOpen={(id) => set({ id, tab: tabOf(byId.get(id)!.kind) })} projects={projects} />}</SheetContent>
      </Sheet>
    </Page>
  )
}
