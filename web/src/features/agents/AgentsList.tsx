// The left column of the Agents page (like the contact list of a chat app): every agent with its face, its name,
// "project · topic", a status dot and its unread count. On top: "New agent", a search field and the grouping
// (by state: waiting for you / to read / running / active / off; by project: one group per project, persisted).
// On a phone it is the whole page at /agents; an agent then opens full screen.
import * as React from 'react'
import { Link, useLocation, useMatch, useSearchParams } from 'react-router'
import { Bot, Plus, Search, X } from 'lucide-react'
import { useT, type TFn } from '@/i18n'
import { agentRoute, useAgents, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { cn, store } from '@/lib/utils'
import { Button, CountBadge, EmptyState, Input, Segmented, Sensitive, Skeleton, StatusDot, useMask } from '@/components/ui'
import { AgentAvatarIcon } from './Avatar'

export type AgentsGrouping = 'state' | 'project'
const GROUPING_KEY = 'mx-agents-grouping'

/** The grouping of the list, kept per browser. */
function useGrouping(): [AgentsGrouping, (g: AgentsGrouping) => void] {
  const [g, setG] = React.useState<AgentsGrouping>(() => (store.get(GROUPING_KEY) === 'project' ? 'project' : 'state'))
  const set = React.useCallback((v: AgentsGrouping) => {
    store.set(GROUPING_KEY, v)
    setG(v)
  }, [])
  return [g, set]
}

export type AgentState = 'waiting' | 'unread' | 'running' | 'failed' | 'active' | 'off'
/** One state per agent, the most pressing first. */
export function agentState(a: Agent): AgentState {
  if ((a.waiting || 0) > 0) return 'waiting'
  if ((a.thread_unread || 0) > 0) return 'unread'
  if ((a.running_now || 0) > 0) return 'running'
  if (!a.enabled) return 'off'
  if (a.last_run?.kind === 'result' && a.last_run.ok === false) return 'failed'
  return 'active'
}

/** Groups "by state": waiting for you, to read, running, active (failed included), off. */
const STATE_GROUPS: { id: string; label: (t: TFn) => string; has: (s: AgentState) => boolean }[] = [
  { id: 'waiting', label: (t) => t('agents.side.waiting'), has: (s) => s === 'waiting' },
  { id: 'unread', label: (t) => t('agents.side.toRead'), has: (s) => s === 'unread' },
  { id: 'running', label: (t) => t('agents.side.running'), has: (s) => s === 'running' },
  { id: 'active', label: (t) => t('agents.side.active'), has: (s) => s === 'active' || s === 'failed' },
  { id: 'off', label: (t) => t('agents.side.off'), has: (s) => s === 'off' },
]

/** Most recent activity first (its last result or skip), then by name. */
const byActivity = (a: Agent, b: Agent) => (b.last_run?.at || b.created || 0) - (a.last_run?.at || a.created || 0) || a.display_name.localeCompare(b.display_name)

export function AgentsList({ onNew, className }: { onNew: () => void; className?: string }) {
  const t = useT()
  const mask = useMask()
  const { data, isLoading, error, refetch } = useAgents()
  const { data: ws } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const [grouping, setGrouping] = useGrouping()
  const [q, setQ] = React.useState('')
  // ?topic=<project>/<topic>: only the agents of that topic (the link from a topic's menu in Sessions).
  const topic = params.get('topic') || ''
  const ql = q.trim().toLowerCase()

  const shown = React.useMemo(() => {
    const all = data?.agents || []
    return all
      .filter((a) => !topic || `${a.project}/${a.topic}` === topic)
      .filter((a) => !ql || [a.display_name, a.name, a.project, a.topic, a.description].some((x) => (x || '').toLowerCase().includes(ql)))
      .sort(byActivity)
  }, [data, topic, ql])

  const groups = React.useMemo(() => {
    if (grouping === 'state')
      return STATE_GROUPS.map((g) => ({ id: g.id, label: g.label(t), emoji: '', agents: shown.filter((a) => g.has(agentState(a))) })).filter((g) => g.agents.length)
    const m = new Map<string, Agent[]>()
    for (const a of [...shown].sort((x, y) => x.topic.localeCompare(y.topic) || x.display_name.localeCompare(y.display_name))) m.set(a.project, [...(m.get(a.project) || []), a])
    // Projects in the order of the workspace (the Sessions tree order).
    const order = (ws?.projects || []).map((p) => p.name)
    return [...m.entries()]
      .sort(([x], [y]) => (order.indexOf(x) + 1 || 1e9) - (order.indexOf(y) + 1 || 1e9) || x.localeCompare(y))
      .map(([p, agents]) => ({ id: p, label: mask(p, 8), emoji: ws?.projects.find((x) => x.name === p)?.emoji || '', agents }))
  }, [grouping, shown, t, ws, mask])

  return (
    <div className={cn('flex min-h-0 flex-col', className)} data-testid="agents-list">
      <div className="grid shrink-0 gap-2 px-3 pt-3 pb-2">
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('agents.side.search')} aria-label={t('agents.side.search')} className="h-8 pl-8 text-[13px]" data-testid="agents-search" />
          </div>
          <Button size="sm" onClick={onNew} className="h-8 shrink-0 max-md:h-10" data-testid="agent-new-side">
            <Plus /> <span className="max-[359px]:sr-only">{t('agents.side.new')}</span>
          </Button>
        </div>
        <Segmented
          size="sm"
          value={grouping}
          onChange={setGrouping}
          aria-label={t('agents.side.grouping')}
          className="w-full [&>button]:flex-1"
          options={[
            { value: 'state', label: t('agents.side.byState') },
            { value: 'project', label: t('agents.side.byProject') },
          ]}
        />
        {topic && (
          <span className="flex min-w-0 items-center gap-1 self-start rounded-full bg-secondary py-0.5 pr-0.5 pl-2.5 text-xs">
            <span className="truncate">
              {t('agents.side.onlyTopic')} <Sensitive length={8}>{topic.replace('/', ' · ')}</Sensitive>
            </span>
            <button
              type="button"
              onClick={() => setParams((p) => (p.delete('topic'), p), { replace: true })}
              className="relative grid size-5 place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground before:absolute before:-inset-2.5 before:content-['']"
              aria-label={t('agents.side.allTopics')}
            >
              <X className="size-3" />
            </button>
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" role="list">
        {isLoading ? (
          <div className="grid gap-1 px-1">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12 rounded-lg" />
            ))}
          </div>
        ) : error ? (
          <EmptyState
            compact
            tone="error"
            title={t('agents.loadError')}
            description={errorMessage(error)}
            action={
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                {t('common.retry')}
              </Button>
            }
          />
        ) : !groups.length ? (
          <EmptyState compact icon={Bot} title={ql || topic ? t('agents.side.noMatch') : t('agents.emptyTitle')} />
        ) : (
          groups.map((g) => (
            <section key={g.id} aria-label={g.label} className="mt-2 first:mt-0">
              <h3 className="flex h-7 items-center gap-1.5 px-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                {g.emoji && <span aria-hidden>{g.emoji}</span>}
                <span className="truncate">{g.label}</span>
                <span className="font-normal tabular-nums">{g.agents.length}</span>
              </h3>
              {g.agents.map((a) => (
                <AgentRow key={a.path} agent={a} showProject={grouping === 'state'} />
              ))}
            </section>
          ))
        )}
      </div>
    </div>
  )
}

const DOT: Record<AgentState, { tone: 'warn' | 'unread' | 'running' | 'error' | 'idle' | 'ok'; pulse?: boolean }> = {
  waiting: { tone: 'warn', pulse: true },
  unread: { tone: 'unread' },
  running: { tone: 'running', pulse: true },
  failed: { tone: 'error' },
  active: { tone: 'ok' },
  off: { tone: 'idle' },
}

function AgentRow({ agent: a, showProject }: { agent: Agent; showProject: boolean }) {
  const t = useT()
  const location = useLocation()
  const to = agentRoute(a)
  // The open agent (its conversation or one of its runs) is highlighted.
  const active = !!useMatch({ path: `${to}/*` })
  const state = agentState(a)
  const dot = DOT[state]
  const unread = a.thread_unread || 0
  return (
    <Link
      role="listitem"
      to={{ pathname: to, search: location.search }}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex min-h-12 items-center gap-2.5 rounded-lg px-2 py-1.5 outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-14',
        active && 'bg-accent hover:bg-accent',
      )}
      data-testid="agents-row"
      data-state={state}
    >
      <span className={cn('relative shrink-0', state === 'off' && 'opacity-60')}>
        <AgentAvatarIcon avatar={a.avatar} size={32} />
        <span className="absolute -right-0.5 -bottom-0.5 grid size-3 place-items-center rounded-full bg-background">
          <StatusDot tone={dot.tone} pulse={dot.pulse} className="size-2" label={t(`agents.side.state.${state}` as 'agents.side.state.active')} />
        </span>
      </span>
      <span className="grid min-w-0 flex-1">
        <span className={cn('truncate text-sm', unread > 0 || state === 'waiting' ? 'font-semibold' : 'font-medium', state === 'off' && 'text-muted-foreground')}>
          <Sensitive length={8}>{a.display_name}</Sensitive>
        </span>
        <span className="truncate text-xs text-muted-foreground">
          <Sensitive length={10}>{showProject ? `${a.project} · ${a.topic}` : a.topic}</Sensitive>
        </span>
      </span>
      <span className="shrink-0 empty:hidden">
        <CountBadge count={unread} title={t('agents.list.unread', { count: unread })} />
      </span>
    </Link>
  )
}
