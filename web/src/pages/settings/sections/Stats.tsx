import * as React from 'react'
import { Link } from 'react-router'
import { BarChart3, RotateCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { qk, useSaveSettings, useSettings, useTokenStats, useUsage } from '@/lib/queries'
import type { TokenCounts, TokenStats, UsageWindow } from '@/lib/types'
import { fmtDate, fmtNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import { Button, EmptyState, ProgressBar, Segmented, Sensitive, Skeleton, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { Chart, compact } from '@/pages/dashboard/charts'
import { SettingsCard, SectionStack } from './ui'

type Group = 'projects' | 'topics' | 'sessions'


function QuotaRow({ label, w }: { label: string; w: UsageWindow | null }) {
  const t = useT()
  const lang = useLang()
  if (!w) return null
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums">
          {Math.round(w.pct)} %
          {w.resets_at && <span className="ml-2 text-xs text-muted-foreground">{t('stats.resets', { at: fmtDate(w.resets_at, lang, undefined, { dateStyle: undefined, timeStyle: undefined, weekday: 'short', hour: '2-digit', minute: '2-digit' }) })}</span>}
        </span>
      </div>
      <ProgressBar value={w.pct} tone={w.pct >= 90 ? 'error' : w.pct >= 70 ? 'warn' : undefined} label={label} />
    </div>
  )
}

function QuotaCard() {
  const t = useT()
  const { data: settings } = useSettings()
  const save = useSaveSettings()
  const on = !!settings?.usage_widget
  const usage = useUsage(on)
  const lang = useLang()
  const fmtRelativeFuture = (at: number) => new Date(at * 1000).toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' })
  /** A sentence for why the plan usage is missing (never a bare error code). */
  const usageReason = (reason: string | undefined, retryAt: number | undefined) => {
    if (!reason) return t('stats.quotaUnavailable')
    if (reason === 'rate_limited') return t('stats.reason.rate_limited', { when: retryAt ? fmtRelativeFuture(retryAt) : '…' })
    if (reason === 'no_oauth_credentials' || reason === 'api_key' || reason === 'http_401') return t(`stats.reason.${reason}` as const)
    return t('stats.reason.other', { code: reason })
  }
  return (
    <SettingsCard title={t('stats.quota')} description={t('stats.quotaDesc')}>
      <SettingRow label={t('stats.quotaEnable')} description={t('stats.quotaEnableDesc')} htmlFor="mx-usage">
        <Switch id="mx-usage" checked={on} disabled={!settings} onCheckedChange={(v) => save.mutate({ usage_widget: v })} />
      </SettingRow>
      {on && (
        <div className="mt-4 grid gap-4">
          {usage.isPending ? (
            <Skeleton className="h-12" />
          ) : usage.data?.available ? (
            <>
              {usage.data.plan && <p className="text-sm text-muted-foreground">{t('stats.plan', { plan: usage.data.plan })}</p>}
              {!usage.data.five_hour && usage.data.plan === 'Ultra' ? (
                <p className="text-sm">{t('stats.noFiveHour')}</p>
              ) : (
                <QuotaRow label={t('stats.fiveHour')} w={usage.data.five_hour} />
              )}
              <QuotaRow label={t('stats.sevenDay')} w={usage.data.seven_day} />
              {usage.data.stale && (
                <p className="text-xs text-muted-foreground">
                  {t('stats.stale')} {usage.data.retry_at ? t('stats.nextReading', { when: fmtRelativeFuture(usage.data.retry_at) }) : null}
                </p>
              )}
            </>
          ) : (
            <Callout tone="info">{usageReason(usage.data?.reason, usage.data?.retry_at)}</Callout>
          )}
        </div>
      )}
    </SettingsCard>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="grid gap-0.5 rounded-lg border bg-muted/20 px-3 py-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tracking-tight tabular-nums">{value}</span>
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  )
}

function rowsOf(data: TokenStats, group: Group, root: string) {
  if (group === 'projects') return data.projects.map((p) => ({ key: p.name || '~', label: p.name || root, href: null as string | null, c: p as Omit<TokenCounts, 'sessions'> & { sessions?: number } }))
  if (group === 'topics') return data.topics.map((tp) => ({ key: tp.path || '~', label: tp.path ? tp.path.replace(/^projects\//, '').replace('/topics/', ' / ') : root, href: `/sessions?path=${encodeURIComponent(tp.path)}`, c: tp }))
  return data.sessions.map((s) => ({ key: s.id, label: s.title, href: `/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`, c: s }))
}

function TokensCard() {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const q = useTokenStats()
  const [group, setGroup] = React.useState<Group>('projects')
  const [refreshing, setRefreshing] = React.useState(false)
  const refresh = async () => {
    setRefreshing(true)
    try {
      qc.setQueryData(qk.stats.tokens, await api.get<TokenStats>('/api/stats/tokens', { force: true }))
    } finally {
      setRefreshing(false)
    }
  }
  const n = (v: number) => compact(v, lang)
  const data = q.data
  const days = data?.days.slice(-30) || []
  return (
    <SettingsCard
      title={t('stats.tokens')}
      description={t('stats.tokensDesc')}
      actions={
        <Button variant="ghost" size="sm" onClick={() => void refresh()} loading={refreshing}>
          <RotateCw /> {t('common.refresh')}
        </Button>
      }
    >
      {q.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-40" />
        </div>
      ) : !data || data.totals.sessions === 0 ? (
        <EmptyState compact icon={BarChart3} title={t('stats.empty')} />
      ) : (
        <div className="grid gap-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Tile label={t('stats.total')} value={n(data.totals.total)} hint={t('stats.turns', { count: data.totals.turns })} />
            <Tile label={t('stats.inOut')} value={`${n(data.totals.input)} / ${n(data.totals.output)}`} />
            <Tile label={t('stats.cache')} value={`${n(data.totals.cache_read)} / ${n(data.totals.cache_write)}`} hint={t('stats.cacheHint')} />
            {data.latency?.start_s != null && (
              <Tile
                label={t('stats.turnStart')}
                value={`${data.latency.start_s.toFixed(2)} s`}
                hint={data.latency.first_answer_s != null ? t('stats.turnStartHint', { first: data.latency.first_answer_s.toFixed(1), count: data.latency.turns }) : undefined}
              />
            )}
          </div>
          {days.length > 1 && (
            <div className="grid gap-1.5">
              <h4 className="text-[13px] font-medium">{t('stats.perDay')}</h4>
              <Chart kind="bar" series={[{ name: t('stats.total'), points: days.map((d) => [d.date.slice(5), d.tokens]) }]} height={150} />
            </div>
          )}
          <div className="grid gap-2">
            <Segmented<Group>
              value={group}
              onChange={setGroup}
              size="sm"
              aria-label={t('stats.groupBy')}
              options={[
                { value: 'projects', label: t('stats.byProject') },
                { value: 'topics', label: t('stats.byTopic') },
                { value: 'sessions', label: t('stats.bySession') },
              ]}
            />
            <div className="-mx-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="px-2 py-1.5 font-medium">{t(group === 'projects' ? 'stats.byProject' : group === 'topics' ? 'stats.byTopic' : 'stats.bySession')}</th>
                    <th className="px-2 py-1.5 text-right font-medium">{t('stats.total')}</th>
                    <th className="px-2 py-1.5 text-right font-medium max-sm:hidden">{t('stats.inOut')}</th>
                    <th className="px-2 py-1.5 text-right font-medium max-md:hidden">{t('stats.cache')}</th>
                    <th className="px-2 py-1.5 text-right font-medium max-sm:hidden">{t('stats.turnsCol')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rowsOf(data, group, t('sessions.root'))
                    .slice(0, 50)
                    .map((r) => {
                      const share = data.totals.total ? r.c.total / data.totals.total : 0
                      return (
                        <tr key={r.key}>
                          <td className="max-w-0 px-2 py-1.5">
                            <div className="flex min-w-0 flex-col gap-1">
                              {r.href ? (
                                <Link to={r.href} className="truncate hover:underline">
                                  <Sensitive length={10}>{r.label}</Sensitive>
                                </Link>
                              ) : (
                                <span className="truncate">
                                  <Sensitive length={10}>{r.label}</Sensitive>
                                </span>
                              )}
                              <span className="h-1 rounded-full bg-primary/70" style={{ width: `${Math.max(2, share * 100)}%` }} aria-hidden />
                            </div>
                          </td>
                          <td className="px-2 py-1.5 text-right font-medium tabular-nums">{n(r.c.total)}</td>
                          <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums max-sm:hidden">
                            {n(r.c.input)} / {n(r.c.output)}
                          </td>
                          <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums max-md:hidden">{n(r.c.cache_read + r.c.cache_write)}</td>
                          <td className={cn('px-2 py-1.5 text-right text-muted-foreground tabular-nums max-sm:hidden')}>{fmtNumber(r.c.turns, lang)}</td>
                        </tr>
                      )
                    })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </SettingsCard>
  )
}

export function StatsSection() {
  return (
    <SectionStack>
      <QuotaCard />
      <TokensCard />
    </SectionStack>
  )
}
