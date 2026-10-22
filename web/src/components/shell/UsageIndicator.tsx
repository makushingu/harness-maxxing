import { useUsage } from '@/lib/queries'
import { useIsMobile } from '@/stores/media'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLang, useT } from '@/i18n'
import type { UsageWindow } from '@/lib/types'
import { ProgressBar, Tooltip } from '@/components/ui'

/** How much of the Claude plan is used (5-hour window, week), as on claude.ai: two small bars under the health indicator.
 *  Hidden when the server has no plan usage (API key, never read). */
export function UsageIndicator({ collapsed, visible }: { collapsed?: boolean; /** Shown in the touch layout's menu (polls while it is open). */ visible?: boolean }) {
  const t = useT()
  const lang = useLang()
  const desktop = !useIsMobile() || !!visible     // the sidebar is hidden in the touch layout: no polling for a bar nobody sees
  const { data: u } = useUsage(desktop, desktop)
  if (!u?.available) return null
  const rows = [
    { key: 'five', label: t('usage.fiveHour'), w: u.five_hour },
    { key: 'week', label: t('usage.week'), w: u.seven_day },
  ].filter((r): r is { key: string; label: string; w: UsageWindow } => !!r.w)
  const used = (w: UsageWindow) => Math.min(100, Math.round(w.pct))
  const tone = (w: UsageWindow) => (used(w) >= 90 ? 'error' : used(w) >= 70 ? 'warn' : undefined)
  const reset = (w: UsageWindow) =>
    w.resets_at ? t('usage.resets', { at: fmtDate(w.resets_at, lang, undefined, { dateStyle: undefined, timeStyle: undefined, weekday: 'short', hour: '2-digit', minute: '2-digit' }) }) : null
  const details = (
    <div className="grid gap-1.5 text-xs">
      <span className="font-medium">{t('usage.title')}</span>
      {rows.map((r) => (
        <span key={r.key} className="tabular-nums">
          {r.label} · {t('usage.used', { pct: used(r.w) })}
          {reset(r.w) && <span className="opacity-70"> · {reset(r.w)}</span>}
        </span>
      ))}
      {u.source === 'turn' && u.seen_at && <span className="max-w-60 opacity-70">{t('usage.seen', { when: fmtRelative(u.seen_at, lang) })}</span>}
    </div>
  )
  return (
    <Tooltip content={details} side="right">
      <div className={cn('grid gap-1.5 px-2.5 py-1.5', collapsed && 'px-1')} aria-label={t('usage.title')}>
        {rows.map((r) =>
          collapsed ? (
            <ProgressBar key={r.key} value={used(r.w)} tone={tone(r.w)} label={r.label} className="h-1" />
          ) : (
            <div key={r.key} className="grid gap-1">
              <div className="flex justify-between text-[11px] leading-none text-muted-foreground">
                <span>{r.label}</span>
                <span className="tabular-nums">{t('usage.used', { pct: used(r.w) })}</span>
              </div>
              <ProgressBar value={used(r.w)} tone={tone(r.w)} label={r.label} className="h-1" />
            </div>
          ),
        )}
      </div>
    </Tooltip>
  )
}
