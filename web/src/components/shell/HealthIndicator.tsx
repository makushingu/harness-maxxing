import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { AlertTriangle, Check, CheckCircle2, ChevronRight, CircleAlert, Cpu, Download, HardDrive, Info, MemoryStick, Monitor, Moon, Sun, Undo2 } from 'lucide-react'
import { useHealth, useMarkHealthSeen } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import type { Health } from '@/lib/types'
import { useUI, type Theme } from '@/stores/ui'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar, Segmented, Sensitive, Skeleton, Switch, Tooltip } from '@/components/ui'
import { useTween } from '@/lib/useTween'
import { MeterBar, MeterIcon, MeterValue, MiniMeter, type MeterTone } from './Meter'
import { ClaudeStatus, usePlanPct, UsageLines } from './UsageIndicator'

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

const meterTone = (pct: number): MeterTone => (pct >= 90 ? 'error' : pct >= 75 ? 'warn' : undefined)

/** CPU, RAM and disk side by side (the status panel): icon and name, the figure counting to its new value, a thin
 *  bar; the bars with every detail are in Settings -> System. 75 % warning, 90 % critical: the colour fades over and
 *  the icon pops once when a line changes level. */
function HealthMeters() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return <Skeleton className="h-10" />
  const mem = h.mem.total ? ((h.mem.total - h.mem.avail) / h.mem.total) * 100 : 0
  const rows = [
    { key: 'cpu', label: t('health.cpu'), pct: h.cpu_pct, icon: Cpu },
    { key: 'mem', label: t('health.ram'), pct: mem, icon: MemoryStick },
    { key: 'disk', label: t('health.disk'), pct: h.disk.pct, icon: HardDrive },
  ]
  return (
    <span className="grid grid-cols-3 gap-3" data-testid="sidebar-meters">
      {rows.map((r) => {
        const tone = meterTone(r.pct)
        return (
          <span key={r.key} className="grid min-w-0 gap-1">
            <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
              <MeterIcon icon={r.icon} tone={tone} />
              <span className="truncate">{r.label}</span>
            </span>
            <Sensitive length={3}>
              <MeterValue pct={r.pct} tone={tone} className="text-sm" />
            </Sensitive>
            <MeterBar pct={r.pct} tone={tone} label={r.label} className="h-1" />
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
  const raw = usePlanPct(visible)
  const tween = Math.round(useTween(raw ?? NaN)) // counts up / down like the panel's figures (not from nothing on load)
  const pct = raw === null ? null : tween
  const health = !h ? t('health.checking') : tone === 'ok' ? t('shell.allGood') : t('health.issues', { count: openIssues(h).length })
  return { tone, health, plan: pct === null ? null : t('shell.claudePct', { pct }), label: pct === null ? health : `${health} · ${t('shell.claudePct', { pct })}` }
}

/** CPU / RAM / disk as the meters need them (null while the health loads). */
function useHealthRows() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return null
  const mem = h.mem.total ? ((h.mem.total - h.mem.avail) / h.mem.total) * 100 : 0
  return [
    { key: 'cpu', label: t('health.cpu'), pct: h.cpu_pct, icon: Cpu },
    { key: 'mem', label: t('health.ram'), pct: mem, icon: MemoryStick },
    { key: 'disk', label: t('health.disk'), pct: h.disk.pct, icon: HardDrive },
  ].map((r) => ({ ...r, tone: meterTone(r.pct) }))
}

const alertBg = { error: 'bg-destructive/10 text-destructive', warn: 'bg-warning/10 text-warning' } as const
const alertHover = {
  error: 'hover:bg-destructive/15 group-hover:bg-destructive/15 data-[state=open]:bg-destructive/15',
  warn: 'hover:bg-warning/15 group-hover:bg-warning/15 data-[state=open]:bg-warning/15',
} as const

/** The bottom of the sidebar: CPU / RAM / disk, then the Claude quota under them.
 *  - Folded bar: three tiny meters (icon + short bar) and the health dot, then the Claude ring marked "✳ Claude".
 *  - Unfolded / pinned: the health line ("All good" with its dot, or "2 problems" in its alert colour) over CPU / RAM /
 *    disk in three columns, then the ring with "Claude quota · Max" and "5 h 47 % · Week 12 %".
 *  Each part keeps the same height folded or not, so nothing above it moves when the bar unfolds. The meters open the
 *  status panel (issues, theme, presentation mode); the Claude entry leads to Settings -> Stats. Same two elements
 *  folded or not, so the keyboard focus survives folding. */
export function StatusBlock({ collapsed }: { collapsed?: boolean }) {
  const s = useStatusLine()
  const rows = useHealthRows()
  const alert = s.tone === 'error' || s.tone === 'warn' ? s.tone : null
  // the panel's links (System, Stats) lead away: close it when the page changes
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => setOpen(false), [pathname])
  const lang = useLang()
  const pct = (n: number) => (lang === 'en' ? `${Math.round(n)}%` : `${Math.round(n)} %`)
  const label = [s.health, ...(rows || []).map((r) => `${r.label} ${pct(r.pct)}`)].join(' · ')
  const tip = (
    <span className="grid gap-0.5 text-xs">
      <span className="font-medium">{s.health}</span>
      {rows?.map((r) => (
        <span key={r.key} className="tabular-nums">
          {r.label} {pct(r.pct)}
        </span>
      ))}
    </span>
  )
  return (
    <div data-testid="sidebar-status" className={cn('grid gap-1 border-t border-sidebar-border px-3 pt-2', collapsed && 'justify-items-center px-2')}>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip content={collapsed ? tip : null} side="right">
          <PopoverTrigger
            data-tour="health"
            data-testid="status-line"
            aria-label={label}
            className={cn(
              'group grid h-[66px] w-full min-w-0 content-center gap-1.5 rounded-md px-1.5 text-left outline-none transition-colors duration-300 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-accent',
              collapsed && 'w-11 justify-items-center px-0',
              collapsed && alert && cn(alertBg[alert], alertHover[alert]),
            )}
          >
            {!rows ? (
              <Skeleton className={collapsed ? 'h-12 w-8' : 'h-12'} />
            ) : collapsed ? (
              <>
                {rows.map((r) => (
                  <MiniMeter key={r.key} icon={r.icon} pct={r.pct} tone={r.tone} label={r.label} />
                ))}
                <span className="mt-0.5 flex size-3 items-center justify-center">
                  <LiveDot tone={s.tone} />
                </span>
              </>
            ) : (
              <>
                {/* the health line: its alert colour while something needs attention (a stronger tint on hover) */}
                <span
                  className={cn(
                    'mx-side-reveal -mx-0.5 flex h-6 min-w-0 items-center gap-2 rounded px-1.5 text-xs font-medium transition-colors duration-500',
                    alert ? cn(alertBg[alert], alertHover[alert]) : 'text-muted-foreground',
                  )}
                >
                  <span className="flex size-4 shrink-0 items-center justify-center">
                    <LiveDot tone={s.tone} />
                  </span>
                  <span className="min-w-0 flex-1 truncate">{s.health}</span>
                  <ChevronRight className="size-3.5 shrink-0 opacity-70" />
                </span>
                <span className="mx-side-reveal grid grid-cols-3 items-center gap-x-3" data-testid="sidebar-meters">
                  {rows.map((r) => (
                    <span key={r.key} className="grid min-w-0 gap-1">
                      <span className="flex min-w-0 items-center gap-1.5 text-xs">
                        <MeterIcon icon={r.icon} tone={r.tone} />
                        <Sensitive length={3}>
                          <MeterValue pct={r.pct} tone={r.tone} render={pct} className="text-xs" />
                        </Sensitive>
                      </span>
                      <MeterBar pct={r.pct} tone={r.tone} label={r.label} className="h-1" />
                    </span>
                  ))}
                </span>
              </>
            )}
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent side="right" align="end" className="w-80 p-3" data-testid="status-panel">
          <StatusPanel />
        </PopoverContent>
      </Popover>
      <ClaudeStatus collapsed={collapsed} />
    </div>
  )
}

const dotTone = { ok: 'bg-success', warn: 'bg-warning', error: 'bg-destructive', idle: 'bg-muted-foreground/50' } as const

/** The status line's dot (also alone in the folded bar): its colour fades over (500 ms) when the health changes,
 *  a slow soft ring breathes out of it while something is critical; instant / still under reduced motion. */
function LiveDot({ tone }: { tone: keyof typeof dotTone }) {
  return (
    <span className="relative inline-flex size-2 shrink-0" aria-hidden>
      <span className={cn('absolute inline-flex size-full rounded-full opacity-0', dotTone[tone], tone === 'error' && 'mx-soft-ping')} />
      <span className={cn('relative inline-flex size-full rounded-full transition-colors duration-500 ease-out motion-reduce:transition-none', dotTone[tone])} />
    </span>
  )
}

const panelRow =
  'flex min-h-9 min-w-0 items-center gap-3 rounded-md px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-11'

/** What the status line opens (the touch menu shows it inline): the health issues or "all good", the Claude plan
 *  (-> Settings -> Stats), CPU / RAM / disk (-> Settings -> System), the theme, presentation mode, Install app. */
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
      <UsageLines visible={touch} className={cn(panelRow, 'grid')} />
      <Link to="/settings/system" className={cn(panelRow, 'grid gap-1.5')} aria-label={t('health.details')} data-testid="status-system">
        <span className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
          {t('health.details')} <ChevronRight className="size-3.5 shrink-0" />
        </span>
        <HealthMeters />
      </Link>
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
