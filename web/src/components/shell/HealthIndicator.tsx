import * as React from 'react'
import { Link } from 'react-router'
import { AlertTriangle, Check, CheckCircle2, ChevronRight, CircleAlert, Cpu, Eye, EyeOff, Globe, HardDrive, Info, MemoryStick, Moon, Sun, TriangleAlert, Undo2 } from 'lucide-react'
import { useBrowserStatus, useCpu, useFeedSettings, useHealth, useMarkHealthSeen, useProfileAction, useSettings } from '@/lib/queries'
import { fmtBytes, fmtDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT, type TKey } from '@/i18n'
import type { CpuSnapshot, Health, HealthIssue } from '@/lib/types'
import { resolveTheme, useUI } from '@/stores/ui'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Popover, PopoverContent, PopoverTrigger, ProgressBar, Sensitive, Skeleton, Tooltip } from '@/components/ui'
import { iconBtn } from './nav'
import { MeterBar, MeterIcon, MeterValue, MiniMeter, type MeterTone } from './Meter'
import { ClaudeStatus } from './UsageIndicator'
import { useMood } from './mood'
import { openMyBrowser } from '@/features/browser/open'

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

/** The status line: one short sentence about the server (`mood.ts`: a problem, the quota that will not last until its
 *  reset, a busy CPU, things left unread... or that all is well), its dot, and where it leads. */
export function useStatusLine() {
  const m = useMood()
  const tone = m.level === 'note' ? 'warn' : m.level
  return { tone, health: m.text, alert: m.level === 'error' || m.level === 'warn' ? m.level : null, issues: !!m.issues, to: m.to, figures: !!(m.vars || m.when) } as const
}

/** CPU / RAM / disk as the meters need them (null while the health loads). The CPU is amber at least while programs
 *  wait for the processor (`waiting`: pressure, not the figure - 99 % with nothing waiting is fine). */
function useHealthRows() {
  const t = useT()
  const { data: h } = useHealth()
  if (!h) return null
  const mem = h.mem.total ? ((h.mem.total - h.mem.avail) / h.mem.total) * 100 : 0
  const waiting = !!h.cpu_waiting
  return [
    { key: 'cpu', label: t('health.cpu'), pct: h.cpu_pct, icon: Cpu, waiting },
    { key: 'mem', label: t('health.ram'), pct: mem, icon: MemoryStick, waiting: false },
    { key: 'disk', label: t('health.disk'), pct: h.disk.pct, icon: HardDrive, waiting: false },
  ].map((r) => ({ ...r, tone: meterTone(r.pct) ?? (r.waiting ? ('warn' as const) : undefined) }))
}

const alertBg = { error: 'bg-destructive/10 text-destructive', warn: 'bg-warning/10 text-warning' } as const
const alertHover = {
  error: 'hover:bg-destructive/15 group-hover:bg-destructive/15 data-[state=open]:bg-destructive/15',
  warn: 'hover:bg-warning/15 group-hover:bg-warning/15 data-[state=open]:bg-warning/15',
} as const

/** The bottom of the sidebar: CPU / RAM / disk, then the Claude quota under them.
 *  - Folded bar: three tiny meters (icon + short bar) and the health dot, then the Claude ring (the sparkle as a faint watermark inside).
 *  - Unfolded / pinned: the status line (a short sentence with its dot, `mood.ts`: "All good", "Running hot! CPU at
 *    92%", a problem in its alert colour; two lines at most) over CPU / RAM /
 *    disk in three columns, then the ring with "Claude quota · Max" and "5 h 47 % · Week 12 %".
 *  Each part keeps the same height folded or not, so nothing above it moves when the bar unfolds. The health line (folded:
 *  the dot) leads to the whole Notifications feed (or Settings -> System when health problems stay out of the feed); while
 *  a problem is open it opens the problems window (`IssuesDialog`) instead,
 *  the meters to Settings -> System, the Claude entry to Settings -> Stats. Under it, the theme and
 *  presentation mode (`SidebarLook`). Same elements folded or not, so the keyboard focus survives folding. */
export function StatusBlock({ collapsed, lead, tail }: { collapsed?: boolean; /** unfolded: Settings, the first icon of the last line */ lead?: React.ReactNode; /** unfolded: Help, at its end */ tail?: React.ReactNode }) {
  const t = useT()
  const s = useStatusLine()
  const rows = useHealthRows()
  const alert = s.alert
  // the line leads to what it talks about, else to the whole Notifications feed (a failed job sits under Crons, not Health) or Settings -> System
  const { data: feedSettings } = useFeedSettings()
  const issuesTo = s.to ?? (feedSettings?.health ? '/feed' : '/settings/system')
  // a problem open: the health line (folded: the dot) opens the problems window instead of leaving the page
  const [open, setOpen] = React.useState(false)
  const present = useUI((u) => u.presentation)
  const lang = useLang()
  const pct = (n: number) => (lang === 'en' ? `${Math.round(n)}%` : `${Math.round(n)} %`)
  const metersLabel = [t('health.details'), ...(rows || []).map((r) => `${r.label} ${pct(r.pct)}`)].join(' · ')
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
  const link = 'outline-none transition-colors duration-300 focus-visible:ring-2 focus-visible:ring-ring'
  return (
    <div data-testid="sidebar-status" data-boot-rv className={cn('grid gap-2 border-t border-sidebar-border px-3 pt-3 pb-[calc(0.75rem+var(--safe-bottom))]', collapsed && 'justify-items-center px-2')}>
      <IssuesDialog open={open} onOpenChange={setOpen} />
      <div data-tour="health" data-testid="status-line" className={cn('grid h-[76px] w-full min-w-0 content-center gap-2', collapsed && 'w-11 justify-items-center')}>
        {!rows ? (
          <Skeleton className={collapsed ? 'h-12 w-8' : 'h-12'} />
        ) : collapsed ? (
          <>
            {/* folded: the CPU mini meter opens who takes the processor, RAM / disk lead to Settings -> System, the
                health dot (only when something is wrong) to the problems */}
            <Tooltip content={tip} side="right">
              <div aria-label={metersLabel} data-testid="status-system" className="grid w-11 justify-items-center gap-0.5">
                {rows.map((r) =>
                  r.key === 'cpu' ? (
                    <CpuWho key={r.key} side="right">
                      <button type="button" aria-label={`${r.label} ${pct(r.pct)} · ${t('health.cpuOpen')}`} data-testid="status-cpu" className={cn(link, 'flex w-11 justify-center rounded-md py-0.5 hover:bg-accent data-[state=open]:bg-accent')}>
                        <MiniMeter icon={r.icon} pct={r.pct} tone={r.tone} label={r.label} />
                      </button>
                    </CpuWho>
                  ) : (
                    <Link key={r.key} to="/settings/system" aria-label={`${r.label} ${pct(r.pct)}`} className={cn(link, 'flex w-11 justify-center rounded-md py-0.5 hover:bg-accent')}>
                      <MiniMeter icon={r.icon} pct={r.pct} tone={r.tone} label={r.label} />
                    </Link>
                  ),
                )}
              </div>
            </Tooltip>
            <span className="flex size-3 items-center justify-center">
              {s.issues ? (
                <Tooltip content={s.health} side="right">
                  <button type="button" onClick={() => setOpen(true)} aria-label={s.health} data-testid="status-issues" className={cn(link, 'flex size-3 items-center justify-center rounded-full')}>
                    <LiveDot tone={s.tone} />
                  </button>
                </Tooltip>
              ) : s.tone === 'warn' ? (
                <Tooltip content={s.health} side="right">
                  <Link to={issuesTo} aria-label={s.health} data-testid="status-issues" className={cn(link, 'flex size-3 items-center justify-center rounded-full')}>
                    <LiveDot tone={s.tone} />
                  </Link>
                </Tooltip>
              ) : null}
            </span>
          </>
        ) : (
          <>
            {/* the health line -> the problems; its alert colour while something needs attention (stronger on hover) */}
            {(() => {
              const cls = cn(
                link,
                'mx-side-reveal flex h-8 w-full min-w-0 items-center gap-2 rounded-md px-1.5 text-left text-xs leading-4 font-medium transition-colors duration-500',
                alert ? cn(alertBg[alert], alertHover[alert]) : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )
              const inner = (
                <>
                  <span className="flex size-4 shrink-0 items-center justify-center">
                    <LiveDot tone={s.tone} />
                  </span>
                  {/* a sentence: two lines at most, the whole of it on hover */}
                  <span data-testid="status-mood" title={present ? undefined : s.health} className="line-clamp-2 min-w-0 flex-1">
                    {s.figures ? <Sensitive length={14}>{s.health}</Sensitive> : s.health}
                  </span>
                </>
              )
              return s.issues ? (
                <button type="button" onClick={() => setOpen(true)} data-testid="status-issues" className={cls}>
                  {inner}
                </button>
              ) : (
                <Link to={issuesTo} data-testid="status-issues" className={cls}>
                  {inner}
                </Link>
              )
            })()}
            {/* CPU -> who takes the processor (a popover); RAM / disk -> Settings -> System. While programs wait for the
                processor the CPU says so ("waiting") instead of its figure. */}
            <div aria-label={metersLabel} data-testid="status-system" className="mx-side-reveal -mx-1.5 grid grid-cols-3 items-center gap-x-1">
              {rows.map((r) => {
                const inner = (
                  <>
                    <span className="flex min-w-0 items-center gap-1.5 text-xs">
                      {/* "waiting" takes the place of the icon and the figure (a third of the bar is narrow) */}
                      {r.waiting ? (
                        <span className="truncate text-xs font-medium text-warning">{t('health.waiting')}</span>
                      ) : (
                        <>
                          <MeterIcon icon={r.icon} tone={r.tone} />
                          <Sensitive length={3}>
                            <MeterValue pct={r.pct} tone={r.tone} render={pct} className="text-xs" />
                          </Sensitive>
                        </>
                      )}
                    </span>
                    <MeterBar pct={r.pct} tone={r.tone} label={r.label} className="h-1" />
                  </>
                )
                const cell = cn(link, 'grid min-w-0 gap-1 rounded-md px-1.5 py-1.5 text-left hover:bg-accent')
                return r.key === 'cpu' ? (
                  <CpuWho key={r.key} side="top">
                    <button type="button" aria-label={`${r.label} ${pct(r.pct)} · ${t('health.cpuOpen')}`} title={present ? undefined : t('health.cpuOpen')} data-testid="status-cpu" className={cn(cell, 'data-[state=open]:bg-accent')}>
                      {inner}
                    </button>
                  </CpuWho>
                ) : (
                  <Link key={r.key} to="/settings/system" aria-label={`${r.label} ${pct(r.pct)}`} className={cell}>
                    {inner}
                  </Link>
                )
              })}
            </div>
          </>
        )}
      </div>
      <ClaudeStatus collapsed={collapsed} />
      <BrowserLine collapsed={collapsed} />
      <SidebarLook collapsed={collapsed} lead={lead} tail={tail} />
    </div>
  )
}

/** The very bottom of the sidebar, under the Claude quota. Unfolded, one line of four icons in the middle (names in
 *  tooltips): Settings (`lead`, a page), a sun / moon that switches between light and dark (it shows the theme on
 *  screen; "System" stays in Settings -> Appearance), the eye of presentation mode (crossed out and tinted while on)
 *  and Help (`tail`). Folded: the sun / moon and the eye one under the other
 *  (Help and Settings keep their rows above). */
function SidebarLook({ collapsed, lead, tail }: { collapsed?: boolean; lead?: React.ReactNode; tail?: React.ReactNode }) {
  const t = useT()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const presentation = useUI((s) => s.presentation)
  const setPresentation = useUI((s) => s.setPresentation)
  const dark = resolveTheme(theme) === 'dark'
  const themeLabel = `${t('shell.theme')} · ${t(dark ? 'theme.dark' : 'theme.light')}`
  const presLabel = presentation ? t('presentation.off') : t('presentation.on')
  const side = collapsed ? 'right' : 'top'
  const buttons = (
    <>
      <Tooltip content={themeLabel} side={side}>
        <button type="button" className={iconBtn()} aria-label={themeLabel} onClick={() => setTheme(dark ? 'light' : 'dark')}>
          {dark ? <Moon /> : <Sun />}
        </button>
      </Tooltip>
      <Tooltip content={presLabel} side={side}>
        <button
          type="button"
          className={cn(iconBtn(), presentation && 'bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary')}
          aria-label={presLabel}
          aria-pressed={presentation}
          onClick={() => setPresentation(!presentation)}
        >
          {presentation ? <EyeOff /> : <Eye />}
        </button>
      </Tooltip>
    </>
  )
  if (collapsed)
    return (
      <div className="grid justify-items-center gap-0.5" data-testid="sidebar-look">
        {buttons}
      </div>
    )
  return (
    <div className="mx-side-reveal mt-0.5 flex h-10 min-w-0 items-center justify-center gap-2" data-testid="sidebar-look">
      {lead}
      {buttons}
      {tail}
    </div>
  )
}

/** The Harness Browser (once on): a click opens my browser's window; while it runs, its memory and tabs; amber with a
 *  "sleep" button when memory runs short. */
function BrowserLine({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  const t = useT()
  const { data: s } = useSettings()
  const { data: st } = useBrowserStatus(!!s?.browser_feature, 30_000)
  const action = useProfileAction()
  const b = st?.summary
  if (!s?.browser_feature || !b) return null
  const warn = b.level !== 'ok'
  const awake = b.running.reduce((n, pid) => n + (b.tabs[pid] || 0), 0)
  const text = [
    t('nav.browser'),
    b.running.length > 1 ? t('browser.profilesOn', { count: b.running.length }) : '',
    b.mem ? fmtBytes(b.mem) : '',
    b.running.length ? t('browser.tabsAwake', { count: awake }) : '',
  ].filter(Boolean).join(' · ')
  return (
    <Tooltip content={warn ? t('browser.memWarn') : collapsed ? text : null} side="right">
      <div className={cn('flex h-8 items-center gap-2 rounded-md px-1.5 text-xs', collapsed && 'w-11 justify-center px-0', warn ? 'text-warning' : 'text-muted-foreground', className)} data-testid="sidebar-browser">
        <button type="button" onClick={() => openMyBrowser()} className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-foreground" aria-label={text} data-testid="sidebar-browser-open">
          {warn ? <TriangleAlert className="size-3.5 shrink-0" /> : <Globe className="size-3.5 shrink-0" />}
          {!collapsed && <span className="truncate">{text}</span>}
        </button>
        {warn && !collapsed && (
          <button type="button" className="shrink-0 underline-offset-2 hover:underline" onClick={() => b.running.forEach((pid) => action.mutate({ profile: pid, action: 'sleep' }))} data-testid="sidebar-browser-sleep">
            {t('browser.sleepShort')}
          </button>
        )}
      </div>
    </Tooltip>
  )
}

/** The CPU meter's window: who takes the processor now (the units using it most, with their priority), how much
 *  programs wait for it, and the way to CPU priorities (Settings -> System). Asked every 3 s while open. */
function CpuWho({ children, side }: { children: React.ReactElement; side: 'top' | 'right' }) {
  const [open, setOpen] = React.useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent side={side} align="start" className="w-80" data-testid="cpu-who">
        {open && <CpuPanel onClose={() => setOpen(false)} />}
      </PopoverContent>
    </Popover>
  )
}

const LEVEL_BADGE = { live: 'success', normal: 'secondary', background: 'muted' } as const

function CpuPanel({ onClose }: { onClose: () => void }) {
  const t = useT()
  const lang = useLang()
  const { data: c } = useCpu(true)
  const pct = (n: number) => (lang === 'en' ? `${Math.round(n)}%` : `${Math.round(n)} %`)
  const name = (u: CpuSnapshot['top'][number]) => {
    if (u.kind === 'other') return u.name || u.unit
    const kind = t(`cpuwho.kind.${u.kind}` as TKey)
    return u.name && u.name !== kind ? `${kind} · ${u.name}` : kind
  }
  return (
    <div className="grid gap-3">
      <div className="grid gap-0.5">
        <p className="text-sm font-semibold">{t('cpuwho.title')}</p>
        {c?.pressure && <p className={cn('text-xs tabular-nums', c.waiting ? 'text-warning' : 'text-muted-foreground')}>{t('cpuwho.pressure', { pct: Math.round(c.pressure.avg10) })}</p>}
      </div>
      {!c ? (
        <Skeleton className="h-24" />
      ) : c.top.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('cpuwho.empty')}</p>
      ) : (
        <ul className="grid gap-2.5" data-testid="cpu-who-list">
          {c.top.map((u) => (
            <li key={u.unit} className="grid gap-1">
              <div className="flex min-w-0 items-center gap-2 text-[13px]">
                <span className="min-w-0 flex-1 truncate" title={u.unit}>
                  <Sensitive length={10}>{name(u)}</Sensitive>
                </span>
                {u.level !== 'other' && <Badge variant={LEVEL_BADGE[u.level]}>{t(`cpuwho.level.${u.level}` as TKey)}</Badge>}
                <span className="w-10 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{pct(u.pct)}</span>
              </div>
              <MeterBar pct={u.pct} tone={undefined} label={name(u)} className="h-1" />
            </li>
          ))}
        </ul>
      )}
      <p className="text-[13px] leading-snug text-muted-foreground">{c && !c.enabled ? t('cpuwho.offHint') : c?.waiting ? t('cpuwho.waitingHint') : t('cpuwho.calm')}</p>
      <Link to="/settings/system" onClick={onClose} className="inline-flex w-fit items-center gap-1 rounded-sm text-[13px] font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
        {t('cpuwho.setting')} <ChevronRight className="size-3.5" />
      </Link>
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

/** Where each kind of problem is fixed (the window's "Open" button). */
const ISSUE_TO: Record<string, string> = {
  disk_full: '/settings/system',
  low_memory: '/settings/system',
  service_down: '/settings/system',
  cron_failed: '/settings/crons',
  login_failures: '/settings/security',
  claude_auth: '/settings/claude',
  backup_never: '/settings/backup',
  backup_old: '/settings/backup',
  backup_failed: '/settings/backup',
  cpu_pressure: '/settings/system',
}

const issueLook = {
  error: { icon: CircleAlert, ring: 'bg-destructive/12 text-destructive', card: 'border-destructive/30 bg-destructive/[0.04]' },
  warn: { icon: AlertTriangle, ring: 'bg-warning/15 text-warning', card: 'border-warning/30 bg-warning/[0.04]' },
  info: { icon: Info, ring: 'bg-muted text-muted-foreground', card: '' },
}

/** The problems window, opened from the health line while something is wrong: one card per open problem (its level,
 *  its text, Open -> where it is fixed, Seen), the problems already seen below and quieter, then the feed and the
 *  system details. */
function IssuesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const { data: h } = useHealth()
  const mark = useMarkHealthSeen()
  const issues = h?.issues || []
  const openOnes = issues.filter((i) => !i.seen)
  const seen = issues.filter((i) => i.seen)
  const worst = openOnes.some((i) => i.level === 'error') ? 'error' : 'warn'
  const card = (i: HealthIssue) => {
    const look = i.seen ? { icon: Check, ring: 'bg-muted text-muted-foreground', card: '' } : issueLook[i.level] || issueLook.info
    const Icon = look.icon
    const to = ISSUE_TO[i.code]
    return (
      <li key={i.id || i.code} data-testid="issue-card" className={cn('flex items-start gap-3 rounded-lg border p-3', look.card, i.seen && 'opacity-70')}>
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', look.ring)}>
          <Icon className="size-4" />
        </span>
        <div className="grid min-w-0 flex-1 gap-2">
          <p className="pt-1.5 text-sm leading-snug [overflow-wrap:anywhere]">{i.text}</p>
          <div className="flex flex-wrap gap-2">
            {to && !i.seen && (
              <Button asChild size="sm" variant="outline" onClick={() => onOpenChange(false)}>
                <Link to={to}>
                  {t('health.open')} <ChevronRight className="size-3.5" />
                </Link>
              </Button>
            )}
            {i.id && (
              <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => mark.mutate({ id: i.id!, seen: !i.seen })}>
                {i.seen ? <><Undo2 className="size-3.5" /> {t('health.unsee')}</> : <><Check className="size-3.5" /> {t('health.markSeen')}</>}
              </Button>
            )}
          </div>
        </div>
      </li>
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="status-panel" className="md:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {openOnes.length ? (
              <AlertTriangle className={cn('size-5 shrink-0', worst === 'error' ? 'text-destructive' : 'text-warning')} />
            ) : (
              <CheckCircle2 className="size-5 shrink-0 text-success" />
            )}
            {openOnes.length ? t('health.issues', { count: openOnes.length }) : t('health.allGood')}
          </DialogTitle>
          <DialogDescription>{t('health.windowHint')}</DialogDescription>
        </DialogHeader>
        {openOnes.length > 0 && <ul className="grid gap-2">{openOnes.map(card)}</ul>}
        {seen.length > 0 && (
          <div className="grid gap-2">
            <p className="text-xs font-medium text-muted-foreground">{t('health.seenTitle')}</p>
            <ul className="grid gap-2">{seen.map(card)}</ul>
          </div>
        )}
        <DialogFooter>
          <Button asChild variant="ghost" onClick={() => onOpenChange(false)}>
            <Link to="/settings/system">{t('health.details')}</Link>
          </Button>
          <Button asChild variant="secondary" onClick={() => onOpenChange(false)}>
            <Link to="/feed">{t('health.allNotifications')}</Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
