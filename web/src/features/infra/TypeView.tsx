// One type of the Infra page (sites, databases, buckets, domains): a bar of where they run, place chips that filter
// (?at=<place>), then one block per place - your servers first, then what is hosted elsewhere.
import * as React from 'react'
import { ArrowUpRight, Cloud, Server } from 'lucide-react'
import type { InfraResource, InfraView } from '@/lib/types'
import { tDyn, useT, type TFn } from '@/i18n'
import { Badge, StatusDot } from '@/components/ui'
import { cn } from '@/lib/utils'
import { KIND_ICON, STATUS_TONE, statusText, subtitle } from './shared'
import { byPlace, otherPlaces, placeInfo, placeOf, type Place } from './places'

const ORDER: Record<string, number> = { down: 0, warn: 1, unknown: 2, ok: 3 }

/** Small coloured tag of a place (this server, a VPS, Cloudflare…). */
export function PlaceTag({ p, className }: { p: Place; className?: string }) {
  return (
    <span
      className={cn('inline-flex h-5 shrink-0 items-center gap-1 rounded-md px-1.5 text-[11.5px] font-medium whitespace-nowrap', className)}
      style={{ color: `color-mix(in oklch, ${p.color} 80%, var(--foreground))`, background: `color-mix(in oklch, ${p.color} 14%, transparent)` }}
    >
      <p.icon className="size-3" />
      {p.label}
    </span>
  )
}

export function PlaceIcon({ p, className }: { p: Place; className?: string }) {
  return (
    <span
      className={cn('grid size-7 shrink-0 place-items-center rounded-lg border', className)}
      style={{ color: p.color, background: `color-mix(in oklch, ${p.color} 14%, transparent)`, borderColor: `color-mix(in oklch, ${p.color} 30%, transparent)` }}
    >
      <p.icon className="size-3.5" />
    </span>
  )
}

/** Thin bar split by place, in the place colours. */
export function MixBar({ parts, className, onPick, current }: { parts: { p: Place; n: number }[]; className?: string; onPick?: (key: string) => void; current?: string | null }) {
  const total = parts.reduce((a, x) => a + x.n, 0) || 1
  return (
    <span className={cn('flex gap-px overflow-hidden rounded-full', className)} aria-hidden={!onPick}>
      {parts.map(({ p, n }) =>
        onPick ? (
          <button
            key={p.key}
            type="button"
            title={`${p.label}: ${n}`}
            aria-label={`${p.label}: ${n}`}
            onClick={() => onPick(p.key)}
            className={cn('h-full transition-opacity hover:opacity-100', current && current !== p.key ? 'opacity-35' : 'opacity-85')}
            style={{ flex: n / total, background: p.color }}
          />
        ) : (
          <i key={p.key} className="block h-full" style={{ flex: n / total, background: p.color }} />
        ),
      )}
    </span>
  )
}

export function ResourceRow({ r, byId, v, onOpen }: { r: InfraResource; byId: Map<string, InfraResource>; v: InfraView; onOpen: () => void }) {
  const t = useT()
  const Icon = KIND_ICON[r.kind]
  const also = otherPlaces(r, byId)
  const bad = r.status === 'down' || r.status === 'warn'
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
        className={cn(
          'grid cursor-pointer grid-cols-[minmax(0,1fr)] items-center gap-x-4 gap-y-0.5 px-3.5 py-2 transition-colors hover:bg-accent/50 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_13rem] pointer-coarse:py-2.5',
          r.hidden && 'opacity-60',
        )}
        data-testid="infra-row"
      >
        <span className="flex min-w-0 items-center gap-2">
          <StatusDot tone={STATUS_TONE[r.status]} label={statusText(r, t)} />
          <span className="truncate text-[13px] font-medium">{r.name}</span>
          {r.kind !== 'site' && r.kind !== 'database' && r.kind !== 'bucket' && r.kind !== 'domain' && (
            <Badge variant="muted" className="shrink-0">
              <Icon className="size-3" /> {tDyn(t, `infra.kind.${r.kind}`, r.kind)}
            </Badge>
          )}
          {r.details.harness && <Badge variant="muted">Harness</Badge>}
          {r.details.sandbox && <Badge variant="muted">{t('infra.sandboxed')}</Badge>}
          {r.details.system && <Badge variant="muted">{t('infra.system')}</Badge>}
        </span>
        <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          {also.map((l) => (
            <PlaceTag key={l} p={placeInfo(l, v, t)} />
          ))}
          <span className="truncate">{r.note ? <i>{r.note}</i> : subtitle(r, t)}</span>
        </span>
        <span className="flex items-center justify-end gap-2 max-md:hidden">
          {bad && <span className={cn('text-xs whitespace-nowrap', r.status === 'down' ? 'text-destructive' : 'text-warning')}>{statusText(r, t)}</span>}
          {r.project && (
            <Badge variant="outline" className="max-w-32 truncate">
              {r.project}
            </Badge>
          )}
          {r.urls[0] ? (
            <a
              href={r.urls[0]}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-primary"
              title={r.urls[0]}
              aria-label={r.urls[0]}
            >
              <ArrowUpRight className="size-3.5" />
            </a>
          ) : (
            <span className="size-6" />
          )}
        </span>
      </div>
    </li>
  )
}

const SHOWN = 40

function PlaceGroup({ p, list, byId, v, onOpen, sub }: { p: Place; list: InfraResource[]; byId: Map<string, InfraResource>; v: InfraView; onOpen: (id: string) => void; sub: string }) {
  const t = useT()
  const [all, setAll] = React.useState(false)
  const sorted = list.slice().sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.name.localeCompare(b.name))
  const down = list.filter((r) => r.status === 'down').length
  const shown = all ? sorted : sorted.slice(0, SHOWN)
  return (
    <section
      className={cn('overflow-hidden rounded-xl border border-l-[3px]', p.tier === 'own' ? 'bg-card' : 'border-dashed [border-left-style:solid]')}
      style={{ borderLeftColor: p.color }}
      data-testid="infra-place"
    >
      <div className="flex items-center gap-3 px-3.5 py-2.5" style={{ background: `color-mix(in oklch, ${p.color} 6%, transparent)` }}>
        <PlaceIcon p={p} />
        <div className="grid min-w-0 flex-1">
          <span className="truncate text-sm font-semibold">{p.label}</span>
          <span className="truncate text-xs text-muted-foreground">{sub}</span>
        </div>
        {down > 0 && <Badge variant="destructive">{t('infra.nDown', { count: down })}</Badge>}
        <span className="text-[13px] font-semibold text-muted-foreground tabular-nums">{list.length}</span>
      </div>
      <ul className="divide-y border-t">
        {shown.map((r) => (
          <ResourceRow key={r.id} r={r} byId={byId} v={v} onOpen={() => onOpen(r.id)} />
        ))}
      </ul>
      {sorted.length > shown.length && (
        <button type="button" onClick={() => setAll(true)} className="w-full border-t px-3.5 py-2 text-left text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground">
          {t('infra.place.more', { count: sorted.length - shown.length })}
        </button>
      )}
    </section>
  )
}

function TierTitle({ tier }: { tier: 'own' | 'hosted' }) {
  const t = useT()
  const Icon = tier === 'own' ? Server : Cloud
  return (
    <h2 className={cn('mt-2 flex items-center gap-2 text-[11.5px] font-semibold tracking-wider uppercase', tier === 'own' ? 'text-primary' : 'text-muted-foreground')}>
      <Icon className="size-3.5" /> {t(tier === 'own' ? 'infra.place.ownTitle' : 'infra.place.hostedTitle')}
      <span className="h-px flex-1 bg-border" />
    </h2>
  )
}

/** Subtitle of a place block: who runs it and how Harness reads it. */
function placeSub(p: Place, v: InfraView, t: TFn, domains: boolean) {
  if (p.tier === 'none') return t('infra.place.noneSub')
  if (domains) return t(p.tier === 'own' ? 'infra.place.pointsOwn' : 'infra.place.pointsHosted', { name: p.label })
  if (p.key === 'local') return t('infra.place.localSub')
  if (p.tier === 'own') return v.sources.servers?.[p.key]?.ok === false ? t('infra.place.sshDown') : t('infra.place.sshSub')
  return t('infra.place.hostedSub', { name: p.label })
}

export function TypeView({ items, v, byId, at, onAt, onOpen, intro }: { items: InfraResource[]; v: InfraView; byId: Map<string, InfraResource>; at: string | null; onAt: (key: string | null) => void; onOpen: (id: string) => void; intro?: React.ReactNode }) {
  const t = useT()
  const domains = items[0]?.kind === 'domain'
  const groups = new Map<string, InfraResource[]>()
  for (const r of items) {
    const k = placeOf(r, byId)
    groups.set(k, [...(groups.get(k) || []), r])
  }
  const keys = [...groups.keys()].sort(byPlace)
  const places = keys.map((k) => placeInfo(k, v, t))
  const parts = places.map((p) => ({ p, n: groups.get(p.key)!.length }))
  const own = parts.filter((x) => x.p.tier === 'own')
  const hosted = parts.filter((x) => x.p.tier !== 'own')
  const cur = at && groups.has(at) ? at : null
  const chip = (x: { p: Place; n: number }) => (
    <button
      key={x.p.key}
      type="button"
      onClick={() => onAt(cur === x.p.key ? null : x.p.key)}
      aria-pressed={cur === x.p.key}
      className={cn('inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs whitespace-nowrap transition-colors hover:bg-accent pointer-coarse:h-9', cur === x.p.key ? 'text-foreground' : 'text-muted-foreground')}
      style={cur === x.p.key ? { borderColor: x.p.color, background: `color-mix(in oklch, ${x.p.color} 14%, transparent)` } : undefined}
    >
      <i className="size-2 rounded-[2px]" style={{ background: x.p.color }} />
      {x.p.label}
      <span className="tabular-nums opacity-70">{x.n}</span>
    </button>
  )
  const sum = (l: typeof parts) => l.reduce((a, x) => a + x.n, 0)
  const shownKeys = cur ? [cur] : keys
  let lastTier = ''
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      {intro}
      <div className="grid gap-2.5">
        <MixBar parts={parts} className="h-2" onPick={(k) => onAt(cur === k ? null : k)} current={cur} />
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => onAt(null)}
            aria-pressed={!cur}
            className={cn('inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs transition-colors hover:bg-accent pointer-coarse:h-9', !cur ? 'bg-secondary text-foreground' : 'text-muted-foreground')}
          >
            {t('infra.place.all')} <span className="tabular-nums opacity-70">{items.length}</span>
          </button>
          {own.length > 0 && (
            <span className="ml-2 inline-flex items-center gap-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase max-sm:hidden">
              <Server className="size-3" /> {t('infra.place.own')} <span className="text-foreground/70">{sum(own)}</span>
            </span>
          )}
          {own.map(chip)}
          {hosted.length > 0 && (
            <span className="ml-2 inline-flex items-center gap-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase max-sm:hidden">
              <Cloud className="size-3" /> {t('infra.place.hosted')} <span className="text-foreground/70">{sum(hosted)}</span>
            </span>
          )}
          {hosted.map(chip)}
        </div>
      </div>
      {shownKeys.map((k) => {
        const p = placeInfo(k, v, t)
        const tier = p.tier === 'none' ? lastTier : p.tier
        const title = !cur && tier !== lastTier && (tier === 'own' || tier === 'hosted') ? <TierTitle key={`t-${tier}`} tier={tier} /> : null
        lastTier = tier
        return (
          <React.Fragment key={k}>
            {title}
            <PlaceGroup p={p} list={groups.get(k)!} byId={byId} v={v} onOpen={onOpen} sub={placeSub(p, v, t, domains)} />
          </React.Fragment>
        )
      })}
    </div>
  )
}

/** Count of each place for a list of resources, ordered (for the nav bars and the overview). */
export function placeCounts(items: InfraResource[], byId: Map<string, InfraResource>) {
  const m = new Map<string, number>()
  for (const r of items) {
    const k = placeOf(r, byId)
    m.set(k, (m.get(k) || 0) + 1)
  }
  return [...m.entries()].sort((a, b) => byPlace(a[0], b[0]))
}
