// Approvals on the Agents page: an agent with `approvals` (or started by outside text) waits for the user before a tool
// call. The request is answered where it shows: in the agent's thread (the card of the request, then what was decided
// in its place), and in the bubble over the agent's desk in the Office (Classic and Space). Extension views of the Office
// only show the "!" (they never decide). Same cards as in a session (pages/sessions/Approvals.tsx), same route.
import * as React from 'react'
import { Link } from 'react-router'
import { Check, Clock, PlayCircle, ShieldCheck, X } from 'lucide-react'
import { useT, type TKey } from '@/i18n'
import { agentRunRoute, usePendingApprovals } from '@/lib/queries'
import type { Agent, AgentMessage, Approval } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Popover, PopoverContent, PopoverTrigger, Sensitive } from '@/components/ui'
import { ApprovalCard } from '@/pages/sessions/Approvals'

/** The requests waiting now for one agent (oldest first). */
export function useAgentApprovals(path: string, enabled = true): Approval[] {
  const { data } = usePendingApprovals(enabled)
  return React.useMemo(() => (data || []).filter((x) => x.agent_path === path && x.status === 'pending'), [data, path])
}

/** Thread messages of the requests: approval id -> its pending request (live) and what was decided (its note). */
export function useThreadApprovals(path: string, msgs: AgentMessage[]) {
  const asked = msgs.some((m) => m.kind === 'approval')
  const pending = useAgentApprovals(path, asked)
  return React.useMemo(() => {
    const live = new Map(pending.map((x) => [x.id, x]))
    const decided = new Map<string, AgentMessage>()
    const requests = new Set<string>()
    for (const m of msgs) {
      if (!m.approval) continue
      if (m.kind === 'approval') requests.add(m.approval)
      else if (m.kind === 'note') decided.set(m.approval, m)
    }
    // A note is drawn inside the card of its request (when the request is in the thread).
    const merged = (m: AgentMessage) => m.kind === 'note' && !!m.approval && requests.has(m.approval)
    return { live, decided, merged }
  }, [pending, msgs])
}

const OUTCOME: Record<string, { icon: typeof Check; tone: string; key: TKey }> = {
  allow: { icon: Check, tone: 'text-success', key: 'agents.approval.allowed' },
  deny: { icon: X, tone: 'text-destructive', key: 'agents.approval.denied' },
  timeout: { icon: Clock, tone: 'text-muted-foreground', key: 'agents.approval.timeout' },
  expired: { icon: Clock, tone: 'text-muted-foreground', key: 'agents.approval.expired' },
}

/** The body of a request in the thread: the card with Allow / Deny while it waits, then one line with the outcome. */
export function ThreadApprovalBody({ m, live, decided }: { m: AgentMessage; live?: Approval; decided?: AgentMessage }) {
  const t = useT()
  if (live) return <ApprovalCard approval={live} className="shadow-none" />
  const st = decided?.status || ''
  const o = OUTCOME[st] || { icon: Clock, tone: 'text-muted-foreground', key: 'agents.approval.closed' as const }
  const Icon = o.icon
  const why = st === 'deny' && decided?.text.match(/\(([^)]*)\)\s*$/)?.[1]
  return (
    <div className="grid min-w-0 gap-1 text-sm" data-testid="agent-approval-done" data-status={st || 'closed'}>
      <p className="min-w-0 truncate font-mono text-[12px] text-muted-foreground">
        <Sensitive>{m.text}</Sensitive>
      </p>
      <span className={cn('inline-flex items-center gap-1 text-xs font-medium', o.tone)}>
        <Icon className="size-3.5" /> {t(o.key)}
        {why && <span className="truncate font-normal text-muted-foreground">· <Sensitive>{why}</Sensitive></span>}
      </span>
    </div>
  )
}

/** The "waiting for your OK" bubble of a desk as a button: it opens the waiting requests with Allow / Deny, without
 *  leaving the Office (the desk itself still opens the agent). */
export function WaitingBubble({ agent: a, className, style, children }: { agent: Agent; className?: string; style?: React.CSSProperties; children: React.ReactNode }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const pending = useAgentApprovals(a.path, true)
  const sid = pending[0]?.session || a.running_sessions?.[0]?.id
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn('cursor-pointer focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', className)}
          style={style}
          onClick={stop}
          onKeyDown={stop}
          onPointerDown={stop}
          draggable={false}
          aria-label={t('agents.approval.open', { name: a.display_name })}
          data-testid="office-approvals"
        >
          {children}
        </button>
      </PopoverTrigger>
      <PopoverContent className="grid w-[26rem] gap-2 p-3" onClick={stop} onKeyDown={stop} data-testid="office-approvals-pop">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <ShieldCheck className="size-4 text-warning" /> {t('agents.conv.waiting', { name: a.display_name })}
        </p>
        {pending.length ? (
          <div className="grid max-h-[60vh] gap-2 overflow-y-auto">
            {pending.map((x) => (
              <ApprovalCard key={x.id} approval={x} className="shadow-none" />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t('agents.approval.none')}</p>
        )}
        {sid && (
          <Link to={agentRunRoute(a.path, sid)} onClick={() => setOpen(false)} className="inline-flex items-center gap-1 text-xs text-primary hover:underline pointer-coarse:min-h-10">
            <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
          </Link>
        )}
      </PopoverContent>
    </Popover>
  )
}
