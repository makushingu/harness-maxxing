import { Link } from 'react-router'
import type * as React from 'react'
import { AlertTriangle, BookOpen, Check, Download, CheckCircle2, CircleAlert, Info, Keyboard, SlidersHorizontal, Undo2 } from 'lucide-react'
import { useHealth, useMarkHealthSeen } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import type { Health } from '@/lib/types'
import { Button, Popover, PopoverContent, PopoverTrigger, ProgressBar, Sensitive, Skeleton, StatusDot, Tooltip } from '@/components/ui'
import { UsageLines } from './UsageIndicator'
import { PresentationToggle, ThemeToggle } from './UserMenu'
import { useShortcutsDialog } from './shortcuts-store'

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
        <ul className="grid gap-1.5">
          {issues.map((i) => (
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

/** The sidebar's status footer (and the touch menu's status card): the health line (a click shows the issues, or
 *  "nothing to report"), CPU / RAM / disk (-> Settings -> System), the Claude plan (-> Settings -> Stats), then the
 *  eye, the theme, the docs, the keyboard shortcuts and General settings. Folded: the dot, the thin plan bars and the three icons. */
export function StatusFooter({ collapsed, touch, onInstall }: { collapsed?: boolean; touch?: boolean; /** touch menu: Install app at the right of the icons */ onInstall?: () => void }) {
  const t = useT()
  const { data: h } = useHealth()
  const tone = healthTone(h)
  const label = !h ? t('health.checking') : tone === 'ok' ? t('health.allGood') : t('health.issues', { count: openIssues(h).length })
  const openShortcuts = useShortcutsDialog((s) => s.setOpen)
  const keyboard = typeof window !== 'undefined' && window.matchMedia('(any-pointer: fine)').matches // shortcuts need a keyboard
  const area = cn(
    'rounded-md px-2.5 py-2 outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
    touch && 'min-h-10 py-2.5 active:bg-accent',
  )
  return (
    <div
      className={cn(
        'grid gap-1',
        !touch && 'border-t border-sidebar-border px-3 pt-3 pb-[calc(0.75rem+var(--safe-bottom))]',
        collapsed && 'justify-items-center px-2.5',
      )}
    >
      <Popover>
        <Tooltip content={collapsed ? label : null} side="right">
          <PopoverTrigger
            data-tour={touch ? undefined : 'health'}
            aria-label={label}
            className={cn(area, 'flex w-full items-center gap-2.5 text-left text-sm text-muted-foreground hover:text-foreground data-[state=open]:bg-accent', touch && 'text-[15px] text-foreground', collapsed && 'size-9 justify-center px-0')}
          >
            <span className="flex size-4 shrink-0 items-center justify-center">
              <StatusDot tone={tone} pulse={tone === 'error'} />
            </span>
            {!collapsed && <span className="truncate">{label}</span>}
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent side={touch ? 'top' : 'right'} align={touch ? 'center' : 'end'} className="w-72">
          <HealthIssues />
        </PopoverContent>
      </Popover>
      {!collapsed && (
        <Link to="/settings/system" className={area} title={t('health.details')}>
          <HealthMeters />
        </Link>
      )}
      <UsageLines collapsed={collapsed} visible={touch} className={cn(area, collapsed && 'flex size-9 items-center justify-center px-0')} />
      <div className={cn('flex items-center gap-1 pt-1', collapsed ? 'flex-col' : 'px-1')}>
        <PresentationToggle />
        <ThemeToggle collapsed={collapsed} />
        <IconLink to="/docs" label={t('nav.docs')} collapsed={collapsed} icon={<BookOpen />} />
        {keyboard && (
          <Tooltip content={t('shortcuts.title')} side={collapsed ? 'right' : 'top'}>
            <Button variant="ghost" size="icon-sm" className="size-8" onClick={() => openShortcuts(true)} aria-label={t('shortcuts.title')}>
              <Keyboard />
            </Button>
          </Tooltip>
        )}
        <IconLink to="/settings/general" label={`${t('nav.settings')} · ${t('settings.general')}`} collapsed={collapsed} icon={<SlidersHorizontal />} />
        {onInstall && (
          <Button variant="ghost" size="sm" className="ml-auto h-8 gap-1.5 px-2.5 text-muted-foreground hover:text-foreground" onClick={onInstall}>
            <Download /> {t('pwa.install')}
          </Button>
        )}
      </div>
    </div>
  )
}

function IconLink({ to, label, icon, collapsed }: { to: string; label: string; icon: React.ReactNode; collapsed?: boolean }) {
  return (
    <Tooltip content={label} side={collapsed ? 'right' : 'top'}>
      <Button asChild variant="ghost" size="icon-sm" className="size-8">
        <Link to={to} aria-label={label}>
          {icon}
        </Link>
      </Button>
    </Tooltip>
  )
}

/** What the health line opens: the issues, or "nothing to report". */
function HealthIssues() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return <Skeleton className="h-4 w-32" />
  if (!h.issues.length)
    return (
      <p className="flex items-center gap-2 text-sm">
        <CheckCircle2 className="size-4 text-success" /> {t('health.nothing')}
      </p>
    )
  return <IssueList issues={h.issues} />
}
