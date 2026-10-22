import { Link } from 'react-router'
import { AlertTriangle, CheckCircle2, CircleAlert, Info } from 'lucide-react'
import { useHealth } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Health } from '@/lib/types'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar, Sensitive, Skeleton, StatusDot, Tooltip } from '@/components/ui'

export function healthTone(h: Health | undefined): 'ok' | 'warn' | 'error' | 'idle' {
  if (!h) return 'idle'
  if (h.issues.some((i) => i.level === 'error')) return 'error'
  if (!h.ok || h.issues.some((i) => i.level === 'warn')) return 'warn'
  return 'ok'
}

/** Health summary used by the sidebar popover and the mobile menu. */
export function HealthSummary({ compact }: { compact?: boolean }) {
  const t = useT()
  const { data: h, isError } = useHealth()
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
        <span className="text-sm font-semibold">{tone === 'ok' ? t('health.allGood') : t('health.issues', { count: h.issues.length })}</span>
      </div>
      {h.issues.length > 0 && (
        <ul className="grid gap-1.5">
          {h.issues.map((i) => (
            <li key={i.code} className="flex items-start gap-2 text-[13px]">
              {i.level === 'error' ? <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : i.level === 'warn' ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" /> : <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
              <span>{i.text}</span>
            </li>
          ))}
        </ul>
      )}
      <div className={cn('grid gap-2.5 border-t pt-3', compact && 'text-[13px]')}>
        <Metric label={t('health.cpu')} value={`${Math.round(h.cpu_pct)}%`} pct={h.cpu_pct} />
        <Metric label={t('health.memory')} value={`${fmtBytes(memUsed)} / ${fmtBytes(h.mem.total)}`} pct={memPct} />
        <Metric label={t('health.disk')} value={`${fmtBytes(h.disk.total - h.disk.free)} / ${fmtBytes(h.disk.total)}`} pct={h.disk.pct} />
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

function Metric({ label, value, pct }: { label: string; value: string; pct: number }) {
  const tone = pct >= 90 ? 'error' : pct >= 75 ? 'warn' : undefined
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

export function HealthIndicator({ collapsed }: { collapsed?: boolean }) {
  const t = useT()
  const { data: h } = useHealth()
  const tone = healthTone(h)
  const label = !h ? t('health.checking') : tone === 'ok' ? t('health.allGood') : t('health.issues', { count: h.issues.length })
  return (
    <Popover>
      <Tooltip content={collapsed ? label : null} side="right">
        <PopoverTrigger
          data-tour="health"
          className={cn(
            'flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
            collapsed && 'justify-center px-0',
          )}
          aria-label={label}
        >
          <span className="flex size-4 items-center justify-center">
            <StatusDot tone={tone} pulse={tone === 'error'} />
          </span>
          {!collapsed && <span className="truncate">{label}</span>}
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent side="right" align="end" className="w-80">
        <HealthSummary />
        <Link to="/settings/system" className="mt-3 block text-[13px] font-medium text-primary hover:underline">
          {t('health.details')}
        </Link>
      </PopoverContent>
    </Popover>
  )
}
