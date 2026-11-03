// Approvals: an agent with `approvals` waits for the user before a tool call that is not pre-allowed. One card per
// waiting request, above the composer of the session (like the plan-ready notice): the tool, its input as the thread
// shows it (the command, the file and its diff), Allow / Deny with an optional message. Server: api/approvals.py.
import * as React from 'react'
import { Check, ShieldQuestion, X } from 'lucide-react'
import { useDecideApproval, useSessionApprovals } from '@/lib/queries'
import type { Approval, Session } from '@/lib/types'
import { fmtDuration } from '@/lib/format'
import { useT } from '@/i18n'
import { Button, Input, Sensitive } from '@/components/ui'
import { ToolInput, toolDiff } from './Items'
import { toolIcon } from './util'

const AGENT_PATH = /^projects\/[^/]+\/topics\/[^/]+\/agents\/[^/]+$/

/** The cards of the session's waiting requests (nothing when none). */
export function ApprovalCards({ session }: { session: Session | undefined }) {
  const maybe = !!session && (AGENT_PATH.test(session.path) || !!session.approvals)
  const { data } = useSessionApprovals(session?.id || '', maybe)
  if (!data?.length) return null
  return (
    <div className="mx-auto grid w-full max-w-(--mx-read,860px) gap-2 px-3 pb-2">
      {data.map((a) => (
        <ApprovalCard key={a.id} approval={a} />
      ))}
    </div>
  )
}

function ApprovalCard({ approval: a }: { approval: Approval }) {
  const t = useT()
  const decide = useDecideApproval()
  const [message, setMessage] = React.useState('')
  const [choice, setChoice] = React.useState<'allow' | 'deny' | null>(null)
  const Icon = toolIcon(a.tool)
  const name = a.tool.startsWith('mcp__') ? a.tool.split('__').slice(2).join('__') || a.tool : a.tool
  const diff = React.useMemo(() => toolDiff(a.tool, a.input), [a.tool, a.input])
  const left = useSecondsLeft(a.expires)
  const send = (decision: 'allow' | 'deny') => {
    setChoice(decision)
    decide.mutate({ id: a.id, decision, message: message.trim() || undefined }, { onSettled: () => setChoice(null) })
  }
  return (
    <div role="group" aria-label={t('approval.title')} className="mx-rise min-w-0 overflow-hidden rounded-lg border border-primary/40 bg-card text-[13px] shadow-xs">
      <div className="flex min-w-0 items-center gap-2 border-b bg-primary/6 px-2.5 py-1.5">
        <ShieldQuestion className="size-3.5 shrink-0 text-primary" />
        <span className="shrink-0 font-medium text-foreground">{t('approval.title')}</span>
        <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
          <Icon className="size-3.5 shrink-0" />
          <span className="truncate font-mono text-[12px]">{name}</span>
        </span>
        {left != null && (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">{t('approval.left', { time: fmtDuration(left) })}</span>
        )}
      </div>
      <div className="grid min-w-0 gap-2 px-2.5 py-2">
        <Sensitive block>
          <ToolInput name={a.tool} input={a.input} diff={diff} display={null} />
        </Sensitive>
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
            <Button size="sm" onClick={() => send('allow')} loading={choice === 'allow'} disabled={decide.isPending}>
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
