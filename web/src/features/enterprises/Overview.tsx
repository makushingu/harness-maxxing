// Tab "Overview": what needs the owner (requests to allow or deny, escalations to answer), cost of the day per department
// against its ceiling, open / late / blocked work, objectives, the latest digest and "Build now" for the reports.
import * as React from 'react'
import { Link } from 'react-router'
import { Check, FileText, X } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { enterpriseRoute, useAnswerEscalation, useBuildReport, useDecideRequest, useEnterpriseEscalations, useEnterpriseOverview, useEnterpriseRequests } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import type { Enterprise, EnterpriseEscalation, EnterpriseObjective, EnterpriseOverview, EnterpriseReport, EnterpriseRequest } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtCost } from '@/pages/sessions/util'
import { Badge, Button, EmptyState, Input, Sensitive, Skeleton, Textarea, toast } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'

export function Overview({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const { data, isLoading, error, refetch } = useEnterpriseOverview(e.id)
  if (isLoading) return <Skeleton className="h-80 rounded-xl" />
  if (error || !data)
    return (
      <EmptyState
        tone="error"
        title={t('ent.overview.loadError')}
        description={errorMessage(error)}
        action={
          <Button variant="outline" onClick={() => void refetch()}>
            {t('common.retry')}
          </Button>
        }
      />
    )
  return (
    <div data-testid="enterprise-overview">
      <SectionStack>
        <NeedsYou enterprise={e} overview={data} />
        <Costs enterprise={e} overview={data} />
        <Work enterprise={e} overview={data} />
        {data.objectives.length > 0 && <Objectives e={e} list={data.objectives} />}
        <Digest enterprise={e} overview={data} />
      </SectionStack>
    </div>
  )
}

const noDept = (t: ReturnType<typeof useT>, id: string, name: string) => (id ? name || id : t('ent.overview.noDepartment'))

/** Requests and escalations waiting for the owner, as cards with their action. */
function NeedsYou({ enterprise: e, overview }: { enterprise: Enterprise; overview: EnterpriseOverview }) {
  const t = useT()
  const requests = useEnterpriseRequests(e.id)
  const escalations = useEnterpriseEscalations(e.id)
  const reqs = (requests.data || []).filter((r) => r.status === 'pending' && r.decider === 'owner')
  const escs = (escalations.data || []).filter((x) => x.status === 'open' && x.to === 'owner')
  const waiting = overview.requests_waiting + overview.escalations_open
  return (
    <SettingsCard title={t('ent.overview.needs')} description={t('ent.overview.needsDesc')} actions={waiting > 0 ? <Badge variant="warning">{waiting}</Badge> : undefined}>
      {overview.in_progress > 0 && (
        <p className="mb-3 text-[13px] text-muted-foreground" data-testid="needs-in-chart">
          {t('ent.overview.inChart', { n: overview.in_progress })}
        </p>
      )}
      {reqs.length + escs.length === 0 ? (
        <p className="text-[13px] text-muted-foreground" data-testid="needs-empty">
          {t('ent.overview.needsNone')}
        </p>
      ) : (
        <ul className="grid gap-3" data-testid="needs-list">
          {reqs.map((r) => (
            <li key={r.id}>
              <RequestCard enterprise={e} request={r} />
            </li>
          ))}
          {escs.map((x) => (
            <li key={x.id}>
              <EscalationCard enterprise={e} escalation={x} />
            </li>
          ))}
        </ul>
      )}
    </SettingsCard>
  )
}

function positionTitle(e: Enterprise, id: string) {
  return e.positions.find((p) => p.id === id)?.title || id
}

/** A request for the owner's decision: Allow or Deny, with an optional reason. */
export function RequestCard({ enterprise: e, request: r }: { enterprise: Enterprise; request: EnterpriseRequest }) {
  const t = useT()
  const lang = useLang()
  const decide = useDecideRequest()
  const [reason, setReason] = React.useState('')
  const go = (decision: 'allow' | 'deny') => decide.mutate({ id: e.id, rid: r.id, decision, reason: reason.trim() }, { onError: (err) => toast.error(errorMessage(err)) })
  return (
    <div className="grid gap-3 rounded-lg border p-3" data-testid="request-card">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">{r.category}</Badge>
        <span>
          <Sensitive length={10}>{positionTitle(e, r.position)}</Sensitive>
        </span>
        {r.amount != null && <span className="tabular-nums">{fmtCost(r.amount)}</span>}
        {r.outside && <Badge variant="warning">{t('ent.outside')}</Badge>}
        <span className="ml-auto">{fmtRelative(r.at, lang)}</span>
      </div>
      <p className="text-sm whitespace-pre-wrap">
        <Sensitive length={30}>{r.text}</Sensitive>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder={t('ent.request.reason')} aria-label={t('ent.request.reason')} maxLength={300} className="min-w-0 flex-1 basis-48" autoComplete="off" />
        <Button size="sm" onClick={() => go('allow')} loading={decide.isPending && decide.variables?.decision === 'allow'} disabled={decide.isPending} data-testid="request-allow">
          <Check /> {t('ent.request.allow')}
        </Button>
        <Button size="sm" variant="outline" onClick={() => go('deny')} loading={decide.isPending && decide.variables?.decision === 'deny'} disabled={decide.isPending} data-testid="request-deny">
          <X /> {t('ent.request.deny')}
        </Button>
      </div>
    </div>
  )
}

/** An escalation that reached the owner: a text field and Answer. */
export function EscalationCard({ enterprise: e, escalation: x }: { enterprise: Enterprise; escalation: EnterpriseEscalation }) {
  const t = useT()
  const lang = useLang()
  const answer = useAnswerEscalation()
  const [text, setText] = React.useState('')
  const send = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!text.trim()) return
    answer.mutate({ id: e.id, esc: x.id, text: text.trim() }, { onSuccess: () => setText(''), onError: (err) => toast.error(errorMessage(err)) })
  }
  return (
    <form onSubmit={send} className="grid gap-3 rounded-lg border p-3" data-testid="escalation-card">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">{t('ent.escalation.level', { level: x.level })}</Badge>
        <span>
          <Sensitive length={10}>{positionTitle(e, x.position)}</Sensitive>
        </span>
        {x.outside && <Badge variant="warning">{t('ent.outside')}</Badge>}
        {x.deadline > 0 && <span>{t('ent.escalation.deadline', { when: fmtRelative(x.deadline, lang) })}</span>}
        <span className="ml-auto">{fmtRelative(x.at, lang)}</span>
      </div>
      <p className="text-sm whitespace-pre-wrap">
        <Sensitive length={30}>{x.text}</Sensitive>
      </p>
      <Textarea value={text} onChange={(ev) => setText(ev.target.value)} placeholder={t('ent.escalation.placeholder')} aria-label={t('ent.escalation.placeholder')} minRows={2} maxRows={8} />
      <div>
        <Button type="submit" size="sm" loading={answer.isPending} disabled={!text.trim()} data-testid="escalation-answer">
          {t('ent.escalation.answer')}
        </Button>
      </div>
    </form>
  )
}

/** A bar of the day's cost against a ceiling (no ceiling: the bar is full width in the muted tone). */
function CostBar({ cost, ceiling, label }: { cost: number; ceiling: number | null; label: string }) {
  const t = useT()
  const over = ceiling != null && ceiling > 0 && cost >= ceiling
  const pct = ceiling ? Math.min(100, (cost / ceiling) * 100) : 0
  return (
    <div className="grid gap-1.5" data-testid="cost-row">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="min-w-0 truncate font-medium">
          <Sensitive length={10}>{label}</Sensitive>
        </span>
        <span className={cn('shrink-0 text-xs text-muted-foreground tabular-nums', over && 'text-destructive')}>
          <Sensitive length={4}>{fmtCost(cost)}</Sensitive>
          {ceiling ? ` / ${fmtCost(ceiling)}` : ` · ${t('ent.overview.noCeiling')}`}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={ceiling || 0}
        aria-valuenow={cost}
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div className={cn('h-full rounded-full', over ? 'bg-destructive' : 'bg-primary')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function Costs({ enterprise: e, overview }: { enterprise: Enterprise; overview: EnterpriseOverview }) {
  const t = useT()
  const total = e.envelope.usd_per_day
  return (
    <SettingsCard title={t('ent.overview.costs')} description={t('ent.overview.costsDesc')}>
      <div className="grid gap-4">
        <CostBar cost={overview.cost_today} ceiling={total} label={t('ent.overview.total')} />
        {overview.departments.length > 0 && <div className="grid gap-4 border-t pt-4">{overview.departments.map((d) => <CostBar key={d.id} cost={d.cost_today} ceiling={d.ceiling} label={noDept(t, d.id, d.name)} />)}</div>}
        {overview.digest_cost > 0 && (
          <p className="text-xs text-muted-foreground">
            {t('ent.overview.digestCost')} <span className="tabular-nums">{fmtCost(overview.digest_cost)}</span>
          </p>
        )}
      </div>
    </SettingsCard>
  )
}

function Tile({ label, value, tone }: { label: string; value: number; tone?: 'warn' | 'bad' }) {
  return (
    <div className="grid gap-0.5 rounded-lg border px-3 py-2.5">
      <span className={cn('text-xl font-semibold tabular-nums', value > 0 && tone === 'warn' && 'text-warning', value > 0 && tone === 'bad' && 'text-destructive')}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function Work({ enterprise: e, overview }: { enterprise: Enterprise; overview: EnterpriseOverview }) {
  const t = useT()
  const sum = (k: 'open_tasks' | 'late_tasks' | 'blocked') => overview.departments.reduce((n, d) => n + d[k], 0)
  return (
    <SettingsCard title={t('ent.overview.work')} description={t('ent.overview.workDesc')}>
      <div className="grid gap-4">
        <div className="grid grid-cols-3 gap-3">
          <Tile label={t('ent.overview.open')} value={sum('open_tasks')} />
          <Tile label={t('ent.overview.late')} value={sum('late_tasks')} tone="bad" />
          <Tile label={t('ent.overview.blocked')} value={sum('blocked')} tone="warn" />
        </div>
        {overview.departments.some((d) => d.open_tasks > 0) && (
          <ul className="divide-y rounded-lg border text-[13px]">
            {overview.departments
              .filter((d) => d.open_tasks > 0)
              .map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
                  <span className="min-w-0 flex-1 truncate font-medium">
                    <Sensitive length={10}>{noDept(t, d.id, d.name)}</Sensitive>
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">{t('ent.overview.deptWork', { open: d.open_tasks, late: d.late_tasks, blocked: d.blocked })}</span>
                </li>
              ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">
          <Link to={enterpriseRoute(e.id, 'decisions')} className="underline underline-offset-2 hover:text-foreground">
            {t('ent.overview.seeDecisions')}
          </Link>
        </p>
      </div>
    </SettingsCard>
  )
}

function Objectives({ e, list }: { e: Enterprise; list: EnterpriseObjective[] }) {
  const t = useT()
  const roots = list.filter((o) => !o.parent || !list.some((x) => x.id === o.parent))
  const row = (o: EnterpriseObjective, depth: number): React.ReactNode => {
    const pct = o.target && o.value != null ? Math.min(100, Math.max(0, (o.value / o.target) * 100)) : null
    return (
      <React.Fragment key={o.id}>
        <li className="grid gap-1.5 py-2.5" style={{ paddingLeft: `${depth * 16}px` }} data-testid="objective-row">
          <div className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="min-w-0 flex-1">
              <Sensitive length={20}>{o.text}</Sensitive>
              {o.owner && <span className="text-xs text-muted-foreground"> · {positionTitle(e, o.owner)}</span>}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{o.target ? `${o.value ?? 0} / ${o.target}${o.unit ? ` ${o.unit}` : ''}` : o.value != null ? `${o.value}${o.unit ? ` ${o.unit}` : ''}` : t('ent.overview.noValue')}</span>
          </div>
          {pct != null && (
            <div role="progressbar" aria-label={o.text} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
            </div>
          )}
        </li>
        {list.filter((c) => c.parent === o.id).map((c) => row(c, depth + 1))}
      </React.Fragment>
    )
  }
  return (
    <SettingsCard title={t('ent.overview.objectives')} description={t('ent.overview.objectivesDesc')}>
      <ul className="divide-y">{roots.map((o) => row(o, 0))}</ul>
    </SettingsCard>
  )
}

function Digest({ enterprise: e, overview }: { enterprise: Enterprise; overview: EnterpriseOverview }) {
  const t = useT()
  const build = useBuildReport()
  const make = (kind: EnterpriseReport['kind']) =>
    build.mutate(
      { id: e.id, kind },
      {
        onSuccess: (r) => toast[r.built ? 'success' : 'info'](t(r.built ? 'ent.reports.built' : 'ent.reports.nothing')),
        onError: (err) => toast.error(errorMessage(err)),
      },
    )
  return (
    <SettingsCard
      title={t('ent.overview.digest')}
      description={overview.digest ? t('ent.overview.digestOf', { date: overview.digest.date }) : t('ent.overview.digestNone')}
      actions={
        <>
          <Button size="sm" variant="outline" onClick={() => make('daily')} loading={build.isPending} data-testid="report-build">
            <FileText /> {t('ent.reports.buildNow')}
          </Button>
          <Button asChild size="sm" variant="ghost">
            <Link to={enterpriseRoute(e.id, 'reports')}>{t('ent.overview.allReports')}</Link>
          </Button>
        </>
      }
    >
      {overview.digest ? (
        <div className="text-sm" data-testid="digest-text">
          <Markdown>{overview.digest.text}</Markdown>
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">{t('ent.overview.digestEmpty')}</p>
      )}
    </SettingsCard>
  )
}
