import { Link } from 'react-router'
import { AlertTriangle, Check, CheckCircle2, CircleAlert, Info, Undo2 } from 'lucide-react'
import { useHealth, useMarkHealthSeen } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Health } from '@/lib/types'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar, Sensitive, Skeleton, StatusDot, Tooltip } from '@/components/ui'
import { usePlanUsage, UsageLines } from './UsageIndicator'
import { PresentationToggle, ThemeToggle } from './UserMenu'

/** Issues not marked as seen: the ones the dot and the count are about. */
export function openIssues(h: Health): Health['issues'] {
  return h.issues.filter((i) => !i.seen)
}

export function healthTone(h: Health | undefined): 'ok' | 'warn' | 'error' | 'idle' {
  if (!h) return 'idle'
  const open = openIssues(h)
  if (open.some((i) => i.level === 'error')) return 'error'
  if (open.some((i) => i.level === 'warn')) return 'warn'
  return 'ok'
}

/** Health summary used by the sidebar popover and the mobile menu. */
export function HealthSummary({ compact, metrics = true }: { compact?: boolean; metrics?: boolean }) {
  const t = useT()
  const { data: h, isError } = useHealth()
  const mark = useMarkHealthSeen()
  if (isError) return <p className="text-sm text-destructive">{t('health.unavailable')}</p>
  if (!h)
    return (
      <div className="grid gap-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    )
  const memUsed = h.mem.total - h.mem.avail
  const memPct = h.mem.total ? (memUsed / h.mem.total) * 100 : 0
  const tone = healthTone(h)
  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2">
        {tone === 'ok' ? <CheckCircle2 className="size-4 text-success" /> : <AlertTriangle className={cn('size-4', tone === 'error' ? 'text-destructive' : 'text-warning')} />}
        <span className="text-sm font-semibold">{tone === 'ok' ? t('health.allGood') : t('health.issues', { count: openIssues(h).length })}</span>
      </div>
      {h.issues.length > 0 && (
        <ul className="grid gap-1.5">
          {h.issues.map((i) => (
            <li key={i.id || i.code} className={cn('group flex items-start gap-2 text-[13px]', i.seen && 'text-muted-foreground')}>
              {i.seen ? <Check className="mt-0.5 size-3.5 shrink-0" /> : i.level === 'error' ? <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : i.level === 'warn' ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" /> : <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
              <span className="min-w-0 flex-1">{i.text}</span>
              {i.id && (
                <Tooltip content={i.seen ? t('health.unsee') : t('health.seenHint')}>
                  <button
                    type="button"
                    onClick={() => mark.mutate({ id: i.id!, seen: !i.seen })}
                    aria-label={i.seen ? t('health.unsee') : t('health.markSeen')}
                    className="-my-0.5 flex h-6 shrink-0 pointer-coarse:h-10 items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {i.seen ? <Undo2 className="size-3.5" /> : <><Check className="size-3.5" /> {t('health.markSeen')}</>}
                  </button>
                </Tooltip>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className={cn('grid gap-2.5 border-t pt-3', compact && 'text-[13px]')}>
        {metrics && (
          <>
            <Metric label={t('health.cpu')} value={`${Math.round(h.cpu_pct)}%`} pct={h.cpu_pct} />
            <Metric label={t('health.memory')} value={`${fmtBytes(memUsed)} / ${fmtBytes(h.mem.total)}`} pct={memPct} />
            <Metric label={t('health.disk')} value={`${fmtBytes(h.disk.total - h.disk.free)} / ${fmtBytes(h.disk.total)}`} pct={h.disk.pct} />
          </>
        )}
        <div className="flex justify-between text-[13px] text-muted-foreground">
          <span>{t('health.uptime')}</span>
          <Sensitive length={4}>
            <span className="text-foreground tabular-nums">{fmtDuration(h.uptime_s)}</span>
          </Sensitive>
        </div>
      </div>
    </div>
  )
}

const meterTone = (pct: number) => (pct >= 90 ? 'error' : pct >= 75 ? 'warn' : undefined)

/** CPU, RAM and disk as figures on one line (the sidebar's status footer); the bars are in Settings -> System. */
function HealthMeters() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return null
  const mem = h.mem.total ? ((h.mem.total - h.mem.avail) / h.mem.total) * 100 : 0
  const rows = [
    { key: 'cpu', label: t('health.cpu'), pct: h.cpu_pct },
    { key: 'mem', label: t('health.ram'), pct: mem },
    { key: 'disk', label: t('health.disk'), pct: h.disk.pct },
  ]
  return (
    <div className="flex justify-between gap-2 text-xs leading-none text-muted-foreground" data-testid="sidebar-meters">
      {rows.map((r) => {
        const tone = meterTone(r.pct)
        return (
          <span key={r.key} className="truncate">
            {r.label}{' '}
            <Sensitive length={3}>
              <span className={cn('tabular-nums text-foreground', tone === 'error' ? 'text-destructive' : tone === 'warn' && 'text-warning')}>{Math.round(r.pct)}%</span>
            </Sensitive>
          </span>
        )
      })}
    </div>
  )
}

function Metric({ label, value, pct }: { label: string; value: string; pct: number }) {
  const tone = meterTone(pct)
  return (
    <div className="grid gap-1">
      <div className="flex justify-between text-[13px]">
        <span className="text-muted-foreground">{label}</span>
        <Sensitive length={5}>
          <span className="tabular-nums">{value}</span>
        </Sensitive>
      </div>
      <ProgressBar value={pct} tone={tone} label={label} />
    </div>
  )
}

/** The sidebar's status footer: health, CPU / RAM / disk, Claude plan usage - one block that opens the details
 *  (issues, uptime, plan resets); the eye and the theme as two small icons beside it. Folded: the dot, the thin
 *  usage bars and the two icons, the meters move into the details. */
export function StatusFooter({ collapsed }: { collapsed?: boolean }) {
  const t = useT()
  const { data: h } = useHealth()
  const usage = usePlanUsage()
  const tone = healthTone(h)
  const label = !h ? t('health.checking') : tone === 'ok' ? t('health.allGood') : t('health.issues', { count: openIssues(h).length })
  return (
    <div className={cn('relative border-t border-sidebar-border px-3 pt-3 pb-[calc(0.75rem+var(--safe-bottom))]', collapsed && 'grid justify-items-center gap-1 px-2.5')}>
      <Popover>
        <Tooltip content={collapsed ? label : null} side="right">
          <PopoverTrigger
            data-tour="health"
            aria-label={label}
            className={cn(
              'grid w-full gap-3 rounded-md px-2.5 py-2.5 text-left outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-accent',
              collapsed && 'justify-items-center px-0',
            )}
          >
            <span className={cn('flex min-w-0 items-center gap-2.5 text-sm text-muted-foreground', !collapsed && 'pr-16')}>
              <span className="flex size-4 shrink-0 items-center justify-center">
                <StatusDot tone={tone} pulse={tone === 'error'} />
              </span>
              {!collapsed && <span className="truncate">{label}</span>}
            </span>
            {!collapsed && <HealthMeters />}
            <UsageLines collapsed={collapsed} />
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent side="right" align="end" className="w-80">
          <HealthSummary metrics={collapsed} />
          {usage && <div className="mt-3 border-t pt-3">{usage.details}</div>}
          <Link to="/settings/system" className="mt-3 block text-[13px] font-medium text-primary hover:underline">
            {t('health.details')}
          </Link>
        </PopoverContent>
      </Popover>
      <div className={cn('flex items-center', collapsed ? 'flex-col gap-1' : 'absolute top-[17px] right-4')}>
        <PresentationToggle />
        <ThemeToggle collapsed={collapsed} />
      </div>
    </div>
  )
}
