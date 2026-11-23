/** A message sent by another session's turn (`maxxing sessions send` / `new`, Jarvis's briefs, the reports of its work
 * board): folded into a small card - who sent it, what it is about - instead of a bubble the owner would take for
 * their own words. A click unfolds the whole text. */
import * as React from 'react'
import { Link } from 'react-router'
import { ChevronRight, ExternalLink, MessagesSquare, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Sensitive, StatusDot, Tooltip } from '@/components/ui'
import type { DotTone } from '@/components/ui/status-dot'
import type { RelayFrom } from '@/lib/types'

const OUTCOME: Record<string, { tone: DotTone; key: 'sessions.relay.done' | 'sessions.relay.asks' | 'sessions.relay.failed' }> = {
  done: { tone: 'ok', key: 'sessions.relay.done' },
  asks: { tone: 'warn', key: 'sessions.relay.asks' },
  failed: { tone: 'error', key: 'sessions.relay.failed' },
}

/** The answers inside the reports (between their <<WORK-x ... WORK-x>> marks), without the instructions for Jarvis. */
export function reportBodies(text: string): string[] {
  const out: string[] = []
  const re = /<<(WORK-[0-9a-f]+)\n([\s\S]*?)\n\1>>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) out.push(m[2].trim())
  return out
}

function firstLine(text: string): string {
  return (text.split('\n').find((l) => l.trim()) || '').trim().slice(0, 200)
}

/** Log lines older than `jarvis` / `reports`: read from the text (reports start with "[Work #N · ", Jarvis's
 * conversations are titled "Jarvis · <date>"). */
function withOldMarks(from: RelayFrom, text: string): RelayFrom {
  if (from.reports || from.jarvis != null) return from
  const ids = [...text.matchAll(/^\[Work #(\d+) · .*\] The session \S+ (finished its turn|FAILED)\./gm)]
  if (ids.length) return { ...from, reports: ids.map((m) => ({ id: Number(m[1]), outcome: m[2] === 'FAILED' ? 'failed' : 'done' })) }
  return /^Jarvis · /.test(from.title) ? { ...from, jarvis: true } : from
}

export function RelayCard({ from: sent, text }: { from: RelayFrom; text: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const from = React.useMemo(() => withOldMarks(sent, text), [sent, text])
  const reports = from.reports || []
  const bodies = reports.length ? reportBodies(text) : []
  const shown = bodies.length ? bodies.join('\n\n---\n\n') : text
  const name = from.title || from.session.slice(0, 8)
  const worst = reports.find((r) => r.outcome === 'failed') || reports.find((r) => r.outcome === 'asks') || reports[0]
  const outcome = worst ? OUTCOME[worst.outcome] || OUTCOME.done : null
  const label = reports.length
    ? reports.length > 1
      ? t('sessions.relay.reports', { n: reports.length })
      : t('sessions.relay.report', { id: reports[0].id, title: name })
    : from.jarvis
      ? t('sessions.relay.fromJarvis')
      : t('sessions.relay.fromSession', { title: name })
  const Icon = from.jarvis || reports.length ? Sparkles : MessagesSquare
  const href = `/sessions?session=${encodeURIComponent(from.session)}`
  return (
    <div
      className={cn(
        'w-full max-w-[min(36rem,100%)] rounded-xl border bg-fill-1 text-[13px] text-muted-foreground transition-colors',
        worst?.outcome === 'asks' && 'border-warning/50',
        worst?.outcome === 'failed' && 'border-destructive/40',
      )}
      data-testid="relay-card"
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-foreground">
          <span className={cn('inline-flex size-6 shrink-0 items-center justify-center rounded-md', from.jarvis || reports.length ? 'bg-primary/10 text-primary' : 'bg-background text-muted-foreground')}>
            <Icon className="size-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              <span className="truncate">{label}</span>
              {outcome && (
                <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-normal text-muted-foreground">
                  <StatusDot tone={outcome.tone} /> {t(outcome.key)}
                </span>
              )}
            </span>
            {!open && <span className="block truncate text-xs">{firstLine(shown)}</span>}
          </span>
          <ChevronRight className={cn('size-4 shrink-0 transition-transform', open && 'rotate-90')} />
        </button>
        <Tooltip content={t('sessions.msg.from', { title: name })}>
          <Link to={href} aria-label={t('sessions.relay.open')} className="inline-flex size-6 shrink-0 items-center justify-center rounded-md hover:bg-accent hover:text-foreground">
            <ExternalLink className="size-3.5" />
          </Link>
        </Tooltip>
      </div>
      {open && (
        <div className="border-t px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap text-secondary-foreground [overflow-wrap:anywhere]">
          <Sensitive block className="bg-transparent">
            {shown}
          </Sensitive>
        </div>
      )}
    </div>
  )
}
