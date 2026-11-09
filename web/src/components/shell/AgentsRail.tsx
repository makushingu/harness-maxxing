// Second column of the unfolded desktop sidebar while the pointer rests on "Agents": the agents grouped by project
// (order and colour of the Agents page, features/agents/layout.tsx), the project's groups first, each with its face,
// its state dot and its unread count. A click opens it and folds the bar; resting on an agent shows its Office card
// (features/agents/AgentHover.tsx). Lazy-loaded with the "agents" texts (Sidebar.tsx).
import * as React from 'react'
import { Link } from 'react-router'
import { Bot } from 'lucide-react'
import { agentRoute, groupRoute, useAgentGroups, useAgents, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { CountBadge, EmptyState, Sensitive, Skeleton, StatusDot, useMask } from '@/components/ui'
import { AgentAvatarIcon, OUTFIT } from '@/features/agents/Avatar'
import { agentState, GroupFace, type AgentState } from '@/features/agents/AgentsList'
import { SilentMark } from '@/features/agents/AgentMenu'
import { useAgentsLayout } from '@/features/agents/layout'
import { AgentHover } from '@/features/agents/AgentHover'

const DOT: Record<AgentState, { tone: 'warn' | 'unread' | 'running' | 'error' | 'idle' | 'ok'; pulse?: boolean }> = {
  waiting: { tone: 'warn', pulse: true },
  unread: { tone: 'unread' },
  running: { tone: 'running', pulse: true },
  failed: { tone: 'error' },
  active: { tone: 'ok' },
  off: { tone: 'idle' },
}

const ROW = 'relative flex min-h-11 items-center gap-2.5 rounded-lg px-2 py-1 outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring'

export default function AgentsRail({ onPick }: { onPick?: () => void }) {
  const t = useT()
  const mask = useMask()
  const { data, isLoading } = useAgents()
  const { data: rooms } = useAgentGroups()
  const { data: ws } = useWorkspace()
  const layout = useAgentsLayout()
  const groups = React.useMemo(() => {
    const byProject = layout.group(data?.agents || [])
    const extra = [...new Set((rooms || []).map((r) => r.project))].filter((p) => !byProject.some((x) => x.project === p))
    return [...byProject, ...extra.map((p) => ({ project: p, agents: [] as Agent[] }))].map((g) => ({
      ...g,
      emoji: ws?.projects.find((x) => x.name === g.project)?.emoji || '',
      rooms: (rooms || []).filter((r) => r.project === g.project),
    }))
  }, [data, rooms, ws, layout])

  return (
    <AgentHover className="h-full">
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-2" role="list" data-testid="agents-rail" onClick={(e) => (e.target as Element).closest('a[href]') && onPick?.()}>
        {isLoading ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="m-1 h-10 rounded-lg" />)
        ) : !groups.length ? (
          <EmptyState compact icon={Bot} title={t('agents.emptyTitle')} />
        ) : (
          groups.map((g) => (
            <section key={g.project} aria-label={g.project} className="mt-2 first:mt-0">
              <h3 className="flex h-7 items-center gap-1.5 px-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: OUTFIT[layout.colorOf(g.project)] }} />
                {g.emoji && <span aria-hidden>{g.emoji}</span>}
                <span className="truncate">{mask(g.project, 8)}</span>
              </h3>
              {g.rooms.map((r) => (
                <Link key={r.path} role="listitem" to={groupRoute(r)} className={ROW}>
                  <GroupFace group={r} size={28} />
                  <span className={cn('min-w-0 flex-1 truncate text-sm', r.unread ? 'font-semibold' : 'font-medium')}>
                    <Sensitive length={8}>{r.display_name}</Sensitive>
                  </span>
                  {r.busy && <StatusDot tone="running" pulse className="size-2" />}
                  <CountBadge count={r.unread} />
                </Link>
              ))}
              {g.agents.map((a) => {
                const state = agentState(a)
                const dot = DOT[state]
                return (
                  <Link key={a.path} role="listitem" to={agentRoute(a)} data-rail-agent className={ROW}>
                    <span className={cn('relative shrink-0', state === 'off' && 'opacity-60')}>
                      <AgentAvatarIcon avatar={a.avatar} size={28} />
                      <span className="absolute -right-0.5 -bottom-0.5 grid size-3 place-items-center rounded-full bg-background">
                        <StatusDot tone={dot.tone} pulse={dot.pulse} className="size-2" label={t(`agents.side.state.${state}` as 'agents.side.state.active')} />
                      </span>
                    </span>
                    <span className="flex min-w-0 flex-1 items-center gap-1">
                      <span className={cn('truncate text-sm', a.thread_unread || state === 'waiting' ? 'font-semibold' : 'font-medium', state === 'off' && 'text-muted-foreground')}>
                        <Sensitive length={8}>{a.display_name}</Sensitive>
                      </span>
                      <SilentMark agent={a} />
                    </span>
                    <CountBadge count={a.thread_unread || 0} />
                  </Link>
                )
              })}
            </section>
          ))
        )}
      </div>
    </AgentHover>
  )
}
