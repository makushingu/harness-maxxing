// ```infra blocks in the chat: Claude names resources, the app shows them live from the Infra snapshot (status, links).
//   site: shop.example.com          (one line per resource: site, database, bucket, domain, server, worker, pages, id)
//   project: acme                   (or filters: project, kind, location - every match, 12 at most)
// Shown only when the Infra page is on (Settings -> Features); otherwise the code stays as it is.
import { Link } from 'react-router'
import { ArrowUpRight, Network } from 'lucide-react'
import { useInfra, useSettings } from '@/lib/queries'
import type { InfraKind, InfraResource } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { CodeBlock, Skeleton, StatusDot } from '@/components/ui'
import { KIND_ICON, STATUS_TONE, locationLabel, rememberServers, statusText } from './shared'

const KINDS: InfraKind[] = ['site', 'database', 'bucket', 'domain', 'server', 'worker', 'pages']
const MAX = 12

export type InfraBlockSpec = { picks: { kind: InfraKind | 'id'; value: string }[]; project?: string; kind?: InfraKind; location?: string }

export function parseInfraBlock(code: string): InfraBlockSpec | null {
  const spec: InfraBlockSpec = { picks: [] }
  for (const line of code.split('\n')) {
    const m = /^\s*(\w+)\s*:\s*(.+?)\s*$/.exec(line)
    if (!m) continue
    const k = m[1].toLowerCase()
    const v = m[2]
    if (k === 'id' || (KINDS as string[]).includes(k)) spec.picks.push({ kind: k as InfraKind | 'id', value: v })
    else if (k === 'project') spec.project = v
    else if (k === 'kind' && (KINDS as string[]).includes(v)) spec.kind = v as InfraKind
    else if (k === 'location' || k === 'server') spec.location = v
  }
  return spec.picks.length || spec.project || spec.kind || spec.location ? spec : null
}

const bare = (s: string) => s.toLowerCase().replace(/^https?:\/\//, '').replace(/\/+$/, '')

export function matchInfra(spec: InfraBlockSpec, all: InfraResource[]): InfraResource[] {
  const out: InfraResource[] = []
  for (const p of spec.picks) {
    const v = bare(p.value)
    const hit =
      p.kind === 'id'
        ? all.find((r) => r.id === p.value)
        : all.find((r) => r.kind === p.kind && (bare(r.name) === v || r.urls.some((u) => bare(u) === v))) ||
          all.find((r) => r.kind === p.kind && bare(r.name).includes(v))
    if (hit && !out.includes(hit)) out.push(hit)
  }
  if (spec.project || spec.kind || spec.location)
    for (const r of all)
      if (
        (!spec.project || r.project === spec.project) &&
        (!spec.kind || r.kind === spec.kind) &&
        (!spec.location || r.location === spec.location) &&
        !r.hidden &&
        !r.details.system &&
        !out.includes(r)
      )
        out.push(r)
  return out.slice(0, MAX)
}

export function InfraBlock({ code, className }: { code: string; className?: string }) {
  const t = useT()
  const { data: settings } = useSettings()
  const on = !!settings?.infra_page
  const spec = parseInfraBlock(code)
  const { data, isLoading } = useInfra(on && !!spec)
  rememberServers(data?.servers)
  if (!spec || !on) return <CodeBlock code={code} language="yaml" className={className} />
  const items = data ? matchInfra(spec, data.resources) : []
  return (
    <div className={cn('not-prose grid gap-1 rounded-xl border bg-card p-2', className)} data-testid="infra-block">
      <Link to="/infra" className="flex items-center gap-1.5 px-1.5 text-xs font-medium text-muted-foreground no-underline hover:text-foreground">
        <Network className="size-3.5" /> {t('infra.title')}
      </Link>
      {isLoading ? (
        <Skeleton className="h-10" />
      ) : !items.length ? (
        <p className="px-1.5 py-1 text-xs text-muted-foreground">{t('infra.blockNone')}</p>
      ) : (
        <ul className="grid">
          {items.map((r) => {
            const Icon = KIND_ICON[r.kind]
            return (
              <li key={r.id} className="flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-accent/50">
                <StatusDot tone={STATUS_TONE[r.status]} label={statusText(r, t)} />
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <Link to={`/infra?id=${encodeURIComponent(r.id)}`} className="truncate font-medium text-foreground no-underline hover:underline">
                  {r.name}
                </Link>
                <span className="shrink-0 text-xs text-muted-foreground">{locationLabel(r.location, t)}</span>
                {r.status !== 'ok' && r.status !== 'unknown' && (
                  <span className={cn('shrink-0 text-xs', r.status === 'down' ? 'text-destructive' : 'text-warning')}>{statusText(r, t)}</span>
                )}
                {r.urls[0] && (
                  <a href={r.urls[0]} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex shrink-0 items-center text-xs text-primary no-underline hover:underline">
                    {t('infra.open')} <ArrowUpRight className="size-3" />
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default InfraBlock
