/** A message the owner did not type - another session's turn, an agent, a scheduled job, a group, an event, the
 * command line, Harness itself: folded into a small card (who sent it, the first line) instead of a bubble the
 * owner would take for their own words. A click unfolds it. One card for every sender; the reports of Jarvis's work
 * board add their number and outcome. */
import * as React from 'react'
import { Link } from 'react-router'
import { Bell, Bot, ChevronRight, Clock, ExternalLink, GitPullRequest, Mail, MessagesSquare, Play, Sparkles, SquareTerminal, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Sensitive, StatusDot, Tooltip } from '@/components/ui'
import type { DotTone } from '@/components/ui/status-dot'
import type { MessageFrom, MessageFromKind } from '@/lib/types'

const OUTCOME: Record<string, { tone: DotTone; key: 'sessions.relay.done' | 'sessions.relay.asks' | 'sessions.relay.failed' }> = {
  done: { tone: 'ok', key: 'sessions.relay.done' },
  asks: { tone: 'warn', key: 'sessions.relay.asks' },
  failed: { tone: 'error', key: 'sessions.relay.failed' },
}

const ICON: Record<MessageFromKind, typeof Bot> = {
  session: MessagesSquare,
  agent: Bot,
  cron: Clock,
  feed: Bell,
  mail: Mail,
  group: Users,
  manual: Play,
  cli: SquareTerminal,
  github: GitPullRequest,
  system: Sparkles,
}

/** Sources whose messages were never typed by the owner: a card even on log lines older than `from`. */
const LEGACY_SOURCES: Record<string, MessageFromKind> = { cron: 'cron', cli: 'cli', github: 'github', system: 'system', browser: 'system' }

/** Who sent a message, or null for the owner's own words. */
export function messageFrom(from: MessageFrom | undefined, source: string | undefined): MessageFrom | null {
  if (from) return from.kind ? from : { ...from, kind: 'session' }
  const kind = source ? LEGACY_SOURCES[source] : undefined
  return kind ? { kind } : null
}

/** The data inside the marked blocks of older messages (<<WORK-x ... WORK-x>> of reports, <<BRIEF-x ... >> of the
 * morning brief), without the instructions for Claude around them. Newer ones carry `shown`. */
export function markedBodies(text: string): string[] {
  const out: string[] = []
  const re = /<<((?:WORK|BRIEF)-[0-9a-f]+)\n([\s\S]*?)\n\1>>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) out.push(m[2].trim())
  return out
}

function firstLine(text: string): string {
  return (text.split('\n').find((l) => l.trim()) || '').trim().slice(0, 200)
}

/** Reports older than `reports` in the log: read from the text (they start with "[Work #N · "). */
function withOldReports(from: MessageFrom, text: string): MessageFrom {
  if (from.reports || from.kind !== 'session') return from
  const ids = [...text.matchAll(/^\[Work #(\d+) · .*\] The session \S+ (finished its turn|FAILED)\./gm)]
  return ids.length ? { ...from, reports: ids.map((m) => ({ id: Number(m[1]), outcome: m[2] === 'FAILED' ? 'failed' : 'done' })) } : from
}

/** Where the card's link goes: the session that sent it, else the agent or the group. */
function senderHref(from: MessageFrom): string | null {
  if (from.session) return `/sessions?session=${encodeURIComponent(from.session)}`
  const p = (from.path || '').replace(/^\/+|\/+$/g, '')
  let m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(p)
  if (from.kind === 'agent' && m) return `/agents/${m[1]}/${m[2]}/${m[3]}`
  m = /^projects\/([^/]+)\/groups\/([^/]+)$/.exec(p)
  if (from.kind === 'group' && m) return `/agents/groups/${m[1]}/${m[2]}`
  return null
}

export function MessageCard({ from: sent, text, shown: given }: { from: MessageFrom; text: string; shown?: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const from = React.useMemo(() => withOldReports(sent, text), [sent, text])
  const reports = from.reports || []
  const shown = React.useMemo(() => {
    if (given?.trim()) return given
    const bodies = markedBodies(text)
    return bodies.length ? bodies.join('\n\n---\n\n') : text
  }, [given, text])
  const name = from.title || (from.session || '').slice(0, 8)
  const worst = reports.find((r) => r.outcome === 'failed') || reports.find((r) => r.outcome === 'asks') || reports[0]
  const outcome = worst ? OUTCOME[worst.outcome] || OUTCOME.done : null
  const label = reports.length
    ? reports.length > 1
      ? t('sessions.relay.reports', { n: reports.length })
      : t('sessions.relay.report', { id: reports[0].id, title: name })
    : name
      ? t(`sessions.from.${from.kind}Named`, { title: name })
      : t(`sessions.from.${from.kind}`)
  const Icon = ICON[from.kind] || MessagesSquare
  const href = senderHref(from)
  return (
    <div
      className={cn(
        'w-full max-w-[min(36rem,100%)] rounded-xl border bg-fill-1 text-[13px] text-muted-foreground transition-colors',
        worst?.outcome === 'asks' && 'border-warning/50',
        worst?.outcome === 'failed' && 'border-destructive/40',
      )}
      data-testid="message-card"
      data-kind={from.kind}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-foreground">
          <span className={cn('inline-flex size-6 shrink-0 items-center justify-center rounded-md', reports.length ? 'bg-primary/10 text-primary' : 'bg-background text-muted-foreground')}>
            <Icon className="size-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-1.5 font-medium text-foreground">
              <span className="min-w-0 truncate">{label}</span>
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
        {href && (
          <Tooltip content={t('sessions.relay.open')}>
            <Link to={href} aria-label={t('sessions.relay.open')} className="inline-flex size-6 shrink-0 items-center justify-center rounded-md hover:bg-accent hover:text-foreground">
              <ExternalLink className="size-3.5" />
            </Link>
          </Tooltip>
        )}
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
