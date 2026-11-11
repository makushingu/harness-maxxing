// Approvals: an agent with `approvals`, or a session whose permission mode is `ask`, waits for the user before a tool
// call that is not pre-allowed ("Always allow" adds the request's rule to the session's topic). One card per
// waiting request, above the composer of the session (like the plan-ready notice): the tool, its input as the thread
// shows it (the command, the file and its diff), Allow / Deny with an optional message. Server: api/approvals.py.
import * as React from 'react'
import { Check, CheckCheck, ShieldQuestion, X } from 'lucide-react'
import { useDecideApproval, useSessionApprovals } from '@/lib/queries'
import type { Approval, Session } from '@/lib/types'
import { fmtDuration } from '@/lib/format'
import { tDyn, useT, type TFn } from '@/i18n'
import { cn } from '@/lib/utils'
import { Button, Input, Sensitive } from '@/components/ui'
import { ToolInput, toolDiff } from './Items'
import { toolIcon } from './util'

const AGENT_PATH = /^projects\/[^/]+\/topics\/[^/]+\/agents\/[^/]+$/

/** The cards of the session's waiting requests (nothing when none). */
export function ApprovalCards({ session }: { session: Session | undefined }) {
  const maybe = !!session && (AGENT_PATH.test(session.path) || !!session.approvals)
  const { data } = useSessionApprovals(session?.id || '', maybe)
  // The one denied first on its own comes first (on top, where the stack starts).
  const cards = React.useMemo(() => [...(data || [])].sort((a, b) => (a.expires ?? Infinity) - (b.expires ?? Infinity)), [data])
  if (!cards.length) return null
  // At most 40 % of the screen's height (30 % on a phone sideways, where one card would be more): the thread and the
  // composer stay in sight, the cards scroll inside.
  return (
    <div className="mx-auto grid max-h-[40dvh] w-full auto-rows-max [@media(max-height:500px)]:max-h-[30dvh] max-w-(--mx-read,860px) shrink-0 gap-2 overflow-y-auto overscroll-contain px-3 pb-2">
      {cards.map((a) => (
        <ApprovalCard key={a.id} approval={a} />
      ))}
    </div>
  )
}

/** One line of an agent's safety change from the server ("sandbox: on -> off", "domains: + a.com"): its field and the
 *  words on / off / (none) in the page's language, the values themselves as they are. */
function changeLine(t: TFn, line: string): string {
  const at = line.indexOf(': ')
  if (at < 0) return line.replace(' -> ', ' → ')
  const key = line.slice(0, at)
  const word = (v: string) => (v === 'on' || v === 'off' ? tDyn(t, `agents.change.${v}`, v) : v === '(none)' ? tDyn(t, 'agents.change.none', v) : v)
  const rest = line.slice(at + 2)
  const vals = /^[+-] /.test(rest) ? rest : rest.split(' -> ').map(word).join(' → ')
  const field = tDyn(t, `agents.change.${key}`, key)
  const out = t('agents.change.line', { field, change: vals })
  return out.includes(vals) ? out : `${field}: ${vals}` // '' while the agents texts download
}

/** One waiting request: the tool and its input, Allow / Deny with an optional message (also in an agent's thread and
 *  in the window of the Office). `plain`: no frame nor title (the window has its own). */
export function ApprovalCard({ approval: a, className, plain }: { approval: Approval; className?: string; plain?: boolean }) {
  const t = useT()
  const decide = useDecideApproval()
  const [message, setMessage] = React.useState('')
  const [choice, setChoice] = React.useState<'allow' | 'deny' | 'always' | null>(null)
  const Icon = toolIcon(a.tool)
  const change = a.kind === 'agent_change'          // an agent's own safety settings: one line per change
  const name = change ? t('approval.agentChange') : a.tool.startsWith('mcp__') ? a.tool.split('__').slice(2).join('__') || a.tool : a.tool
  const diff = React.useMemo(() => toolDiff(a.tool, a.input), [a.tool, a.input])
  const left = useSecondsLeft(a.expires)
  const send = (decision: 'allow' | 'deny', always = false) => {
    setChoice(always ? 'always' : decision)
    decide.mutate({ id: a.id, decision, message: message.trim() || undefined, always }, { onSettled: () => setChoice(null) })
  }
  return (
    <div role="group" aria-label={t('approval.title')} className={cn('min-w-0 text-[13px]', !plain && 'mx-rise overflow-hidden rounded-lg border border-primary/40 bg-card shadow-xs', className)}>
      {/* Narrow card: the countdown goes to its own line (and wraps), then the title gives way; the tool name never does. */}
      <div className={cn('flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5', plain ? 'pb-2' : 'border-b bg-primary/6 px-2.5 py-1.5')}>
        {!plain && <ShieldQuestion className="size-3.5 shrink-0 text-primary" />}
        {!plain && <span className="min-w-0 truncate font-medium text-foreground">{t('approval.title')}</span>}
        <span className="flex max-w-full shrink-0 items-center gap-1.5 text-muted-foreground" title={a.tool}>
          <Icon className="size-3.5 shrink-0" />
          <span className="truncate font-mono text-[12px]">{name}</span>
        </span>
        {left != null && (
          <span className="ml-auto max-w-full text-xs text-muted-foreground tabular-nums">{t('approval.left', { time: fmtDuration(left) })}</span>
        )}
      </div>
      <div className={cn('grid min-w-0 gap-2', !plain && 'px-2.5 py-2')}>
        <Sensitive block>
          {change ? (
            <ul className="grid gap-0.5 font-mono text-[12px]" data-testid="approval-agent-change">
              {String(a.input.description || '').split('; ').map((x, i) => (
                <li key={i} className="break-words">{changeLine(t, x)}</li>
              ))}
            </ul>
          ) : (
            <ToolInput name={a.tool} input={a.input} diff={diff} display={null} />
          )}
        </Sensitive>
        {a.clipped && <p className="text-xs text-warning">{t('approval.clipped')}</p>}
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing && message.trim()) send('deny')
            }}
            maxLength={1000}
            placeholder={t('approval.messagePlaceholder')}
            aria-label={t('approval.messagePlaceholder')}
            className="h-8 min-w-40 flex-1 text-[13px]"
          />
          <span className="ml-auto flex shrink-0 items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => send('deny')} loading={choice === 'deny'} disabled={decide.isPending}>
              <X className="size-3.5" /> {t('approval.deny')}
            </Button>
            {!!a.always_rule && !a.clipped && (
              <Button size="sm" variant="outline" onClick={() => send('allow', true)} loading={choice === 'always'} disabled={decide.isPending} title={t('approval.alwaysTitle', { rule: a.always_rule })}>
                <CheckCheck className="size-3.5" /> {t('approval.always')}
              </Button>
            )}
            <Button size="sm" onClick={() => send('allow')} loading={choice === 'allow'} disabled={decide.isPending || a.clipped}>
              <Check className="size-3.5" /> {t('approval.allow')}
            </Button>
          </span>
        </div>
      </div>
    </div>
  )
}

/** Seconds before the request is denied on its own (refreshed every 15 s; null when unknown). */
function useSecondsLeft(expires: number | null): number | null {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    if (!expires) return
    const id = window.setInterval(() => setNow(Date.now() / 1000), 15000)
    return () => window.clearInterval(id)
  }, [expires])
  return expires ? Math.max(0, Math.round((expires - now) / 60) * 60) : null
}
