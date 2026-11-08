import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { AlertTriangle, Check, CheckCircle2, ChevronRight, CircleAlert, Download, Info, Monitor, Moon, Sun, Undo2 } from 'lucide-react'
import { useHealth, useMarkHealthSeen } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Health } from '@/lib/types'
import { useUI, type Theme } from '@/stores/ui'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar, Segmented, Sensitive, Skeleton, StatusDot, Switch, Tooltip } from '@/components/ui'
import { usePlanPct, UsageLines } from './UsageIndicator'

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

/** Health summary with the CPU / RAM / disk bars (Settings -> System). */
export function HealthSummary({ compact, metrics = true }: { compact?: boolean; metrics?: boolean }) {
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
        <span className="text-sm font-semibold">{tone === 'ok' ? t('health.allGood') : t('health.issues', { count: openIssues(h).length })}</span>
      </div>
      {h.issues.length > 0 && <IssueList issues={h.issues} />}
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

/** The health issues, each with its Seen toggle (the popover of the sidebar, Settings -> System). */
function IssueList({ issues }: { issues: Health['issues'] }) {
  const t = useT()
  const mark = useMarkHealthSeen()
  return (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
          {issues.map((i) => (
            <li key={i.id || i.code} className={cn('group flex items-start gap-2 text-[13px]', i.seen && 'text-muted-foreground')}>
              {i.seen ? <Check className="mt-0.5 size-3.5 shrink-0" /> : i.level === 'error' ? <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : i.level === 'warn' ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" /> : <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{i.text}</span>
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
  )
}

const meterTone = (pct: number) => (pct >= 90 ? 'error' : pct >= 75 ? 'warn' : undefined)

/** CPU, RAM and disk as three figures side by side (the status panel); the bars are in Settings -> System. */
function HealthMeters() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return <Skeleton className="h-8" />
  const mem = h.mem.total ? ((h.mem.total - h.mem.avail) / h.mem.total) * 100 : 0
  const rows = [
    { key: 'cpu', label: t('health.cpu'), pct: h.cpu_pct },
    { key: 'mem', label: t('health.ram'), pct: mem },
    { key: 'disk', label: t('health.disk'), pct: h.disk.pct },
  ]
  return (
    <span className="grid grid-cols-3 gap-2" data-testid="sidebar-meters">
      {rows.map((r) => {
        const tone = meterTone(r.pct)
        return (
          <span key={r.key} className="grid min-w-0 gap-0.5">
            <span className="truncate text-xs text-muted-foreground">{r.label}</span>
            <Sensitive length={3}>
              <span className={cn('text-sm tabular-nums', tone === 'error' ? 'text-destructive' : tone === 'warn' && 'text-warning')}>{Math.round(r.pct)}%</span>
            </Sensitive>
          </span>
        )
      })}
    </span>
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

/** The status line's text: "All good · Claude 47 %", the issue count instead of "All good" when something needs
 *  attention, no Claude part without plan usage. */
export function useStatusLine(visible?: boolean) {
  const t = useT()
  const { data: h } = useHealth()
  const tone = healthTone(h)
  const pct = usePlanPct(visible)
  const health = !h ? t('health.checking') : tone === 'ok' ? t('shell.allGood') : t('health.issues', { count: openIssues(h).length })
  return { tone, health, plan: pct === null ? null : t('shell.claudePct', { pct }), label: pct === null ? health : `${health} · ${t('shell.claudePct', { pct })}` }
}

/** The sidebar's last line: one dot coloured by the health and "All good · Claude 47 %" (folded: the dot alone).
 *  A click opens the status panel. */
export function StatusLine({ collapsed }: { collapsed?: boolean }) {
  const s = useStatusLine()
  const alert = s.tone === 'error' || s.tone === 'warn'
  // the panel's links (System, Stats) lead away: close it when the page changes
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => setOpen(false), [pathname])
  return (
    <div className={cn('border-t border-sidebar-border px-3 pt-2 pb-[calc(0.5rem+var(--safe-bottom))]', collapsed && 'flex justify-center px-2.5')}>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip content={collapsed ? s.label : null} side="right">
          <PopoverTrigger
            data-tour="health"
            data-testid="status-line"
            aria-label={s.label}
            className={cn(
              'flex h-9 w-full min-w-0 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px] text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-accent',
              alert && (s.tone === 'error' ? 'bg-destructive/10 text-destructive' : 'bg-warning/10 text-warning'),
              collapsed && 'size-9 justify-center px-0',
            )}
          >
            <span className="flex size-4 shrink-0 items-center justify-center">
              <StatusDot tone={s.tone} pulse={s.tone === 'error'} />
            </span>
            {!collapsed && (
              <span className="min-w-0 flex-1 truncate">
                {s.health}
                {s.plan && <span className="text-muted-foreground"> · <Sensitive length={3}>{s.plan}</Sensitive></span>}
              </span>
            )}
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent side="right" align="end" className="w-80 p-3" data-testid="status-panel">
          <StatusPanel />
        </PopoverContent>
      </Popover>
    </div>
  )
}

const panelRow =
  'flex min-h-9 min-w-0 items-center gap-3 rounded-md px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-11'

/** What the status line opens (the touch menu shows it inline): the health issues or "all good", CPU / RAM / disk
 *  (-> Settings -> System), the Claude plan (-> Settings -> Stats), the theme, presentation mode, Install app. */
export function StatusPanel({ touch, onInstall }: { touch?: boolean; /** touch menu: Install app */ onInstall?: () => void }) {
  const t = useT()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const presentation = useUI((s) => s.presentation)
  const setPresentation = useUI((s) => s.setPresentation)
  return (
    <div className="grid min-w-0 gap-1">
      <div className="px-2 pt-0.5 pb-1.5">
        <HealthIssues />
      </div>
      <Link to="/settings/system" className={cn(panelRow, 'grid gap-1.5')} aria-label={t('health.details')}>
        <span className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
          {t('health.details')} <ChevronRight className="size-3.5 shrink-0" />
        </span>
        <HealthMeters />
      </Link>
      <UsageLines visible={touch} className={cn(panelRow, 'grid')} />
      <div className="mt-1 grid gap-1 border-t pt-2">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-2 py-1">
          <span className="text-sm">{t('shell.theme')}</span>
          <Segmented<Theme>
            size="sm"
            value={theme}
            onChange={setTheme}
            aria-label={t('shell.theme')}
            options={[
              { value: 'light', label: <><Sun /><span className="sr-only">{t('theme.light')}</span></> },
              { value: 'dark', label: <><Moon /><span className="sr-only">{t('theme.dark')}</span></> },
              { value: 'system', label: <><Monitor /><span className="sr-only">{t('theme.system')}</span></> },
            ]}
          />
        </div>
        <label className={cn(panelRow, 'cursor-pointer justify-between hover:bg-transparent')}>
          <span className="min-w-0">{t('presentation.label')}</span>
          <Switch checked={presentation} onCheckedChange={setPresentation} />
        </label>
        {onInstall && (
          <button type="button" className={cn(panelRow, 'w-full text-left')} onClick={onInstall}>
            <Download className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">{t('pwa.install')}</span>
          </button>
        )}
      </div>
    </div>
  )
}

/** The panel's first lines: "All systems normal", or the issue count and the issues (each with its Seen toggle). */
function HealthIssues() {
  const t = useT()
  const { data: h, isError } = useHealth()
  if (isError) return <p className="text-sm text-destructive">{t('health.unavailable')}</p>
  if (!h) return <Skeleton className="h-4 w-32" />
  const tone = healthTone(h)
  return (
    <div className="grid gap-2">
      <p className="flex items-center gap-2 text-sm font-medium">
        {tone === 'ok' ? <CheckCircle2 className="size-4 shrink-0 text-success" /> : <AlertTriangle className={cn('size-4 shrink-0', tone === 'error' ? 'text-destructive' : 'text-warning')} />}
        {tone === 'ok' ? t('health.allGood') : t('health.issues', { count: openIssues(h).length })}
      </p>
      {h.issues.length > 0 && <IssueList issues={h.issues} />}
    </div>
  )
}
