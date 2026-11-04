// The left column of the Agents page (like the contact list of a chat app): every agent with its face, its name, its
// topic, a status dot and its unread count, always grouped by project (order and colour of layout.tsx: drag a project
// header or an agent to move it, the "..." of a project for Move up / down and its colour). On top: the search field,
// "New agent", then `nav` (the Office entry of AgentsLayout), then the state filter (All / waiting for you / to read
// / running / active / off, with counts; empty states hidden) and the ?topic= chip.
// On a phone it is the whole page at /agents; an agent then opens full screen.
import * as React from 'react'
import { Link, useLocation, useMatch, useSearchParams } from 'react-router'
import { Bot, Plus, Search, X } from 'lucide-react'
import { useT, type TFn } from '@/i18n'
import { agentRoute, useAgents, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button, CountBadge, EmptyState, Input, Sensitive, Skeleton, StatusDot, useMask, type DotTone } from '@/components/ui'
import { useCompact } from '@/stores/media'
import { AgentAvatarIcon, OUTFIT } from './Avatar'
import { DropBar, ProjectMenu, useAgentsLayout, useReorder, type AgentsLayoutApi } from './layout'

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

/** The state filter: waiting for you, to read, running, active (failed included), off. */
type StateFilter = 'waiting' | 'unread' | 'running' | 'active' | 'off'
const STATE_GROUPS: { id: StateFilter; tone: DotTone; label: (t: TFn) => string; has: (s: AgentState) => boolean }[] = [
  { id: 'waiting', tone: 'warn', label: (t) => t('agents.side.waiting'), has: (s) => s === 'waiting' },
  { id: 'unread', tone: 'unread', label: (t) => t('agents.side.toRead'), has: (s) => s === 'unread' },
  { id: 'running', tone: 'running', label: (t) => t('agents.side.running'), has: (s) => s === 'running' },
  { id: 'active', tone: 'ok', label: (t) => t('agents.side.active'), has: (s) => s === 'active' || s === 'failed' },
  { id: 'off', tone: 'idle', label: (t) => t('agents.side.off'), has: (s) => s === 'off' },
]

/** Most recent activity first (its last result or skip), then by name. */
const byActivity = (a: Agent, b: Agent) => (b.last_run?.at || b.created || 0) - (a.last_run?.at || a.created || 0) || a.display_name.localeCompare(b.display_name)

/** `empty`: shown instead of the short "No agent yet" when there is no agent at all (the touch layout, where the list
 *  is the whole page). `nav`: entries between "New agent" and the filter (the Office). */
export function AgentsList({ onNew, empty, nav, className }: { onNew: () => void; empty?: React.ReactNode; nav?: React.ReactNode; className?: string }) {
  const t = useT()
  const mask = useMask()
  const touch = useCompact()
  const { data, isLoading, error, refetch } = useAgents()
  const { data: ws } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = React.useState<StateFilter | null>(null)
  const [q, setQ] = React.useState('')
  // ?topic=<project>/<topic>: only the agents of that topic (the link from a topic's menu in Sessions).
  const topic = params.get('topic') || ''
  const ql = q.trim().toLowerCase()

  // The topic chip and the search narrow first; the state chips count what is left.
  const matching = React.useMemo(() => {
    const all = data?.agents || []
    return all
      .filter((a) => !topic || `${a.project}/${a.topic}` === topic)
      .filter((a) => !ql || [a.display_name, a.name, a.project, a.topic, a.description].some((x) => (x || '').toLowerCase().includes(ql)))
      .sort(byActivity)
  }, [data, topic, ql])
  const counts = React.useMemo(() => {
    const c = {} as Record<StateFilter, number>
    for (const g of STATE_GROUPS) c[g.id] = matching.filter((a) => g.has(agentState(a))).length
    return c
  }, [matching])
  const shown = React.useMemo(() => {
    const g = STATE_GROUPS.find((x) => x.id === filter)
    return g ? matching.filter((a) => g.has(agentState(a))) : matching
  }, [matching, filter])

  const layout = useAgentsLayout()
  const groups = React.useMemo(
    () => layout.group(shown).map(({ project: p, agents }) => ({ id: p, label: mask(p, 8), emoji: ws?.projects.find((x) => x.name === p)?.emoji || '', agents })),
    [shown, ws, mask, layout],
  )
  const shownProjects = groups.map((g) => g.id)

  return (
    <div className={cn('flex min-h-0 flex-col', className)} data-testid="agents-list">
      <div className={cn('grid shrink-0 gap-2 px-3 pt-3', touch ? 'pb-1' : 'pb-2')}>
        <div className="relative min-w-0">
          <Search className={cn('pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground', touch ? 'left-3 size-[18px]' : 'left-2.5 size-3.5')} />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && (setQ(''), e.currentTarget.blur())}
            placeholder={t('agents.side.search')}
            aria-label={t('agents.side.search')}
            className={cn('border-0 bg-muted dark:bg-muted', touch ? 'h-11 rounded-xl pl-10' : 'h-8 rounded-lg pl-8 text-[13px]')}
            data-testid="agents-search"
          />
        </div>
        <Button size="sm" onClick={onNew} className={cn('w-full', touch ? 'h-11 rounded-xl' : 'h-8')} data-testid="agent-new-side">
          <Plus /> {t('agents.side.new')}
        </Button>
      </div>
      {nav}
      <div className="grid shrink-0 gap-2 px-3 pt-2 pb-1.5">
        <div className={cn('flex min-w-0 gap-1.5', touch ? '-my-1 overflow-x-auto py-1' : 'flex-wrap')} role="group" aria-label={t('agents.side.filter')} data-hscroll-ok data-testid="agents-filter">
          <button type="button" className={chip(!filter, touch)} aria-pressed={!filter} onClick={() => setFilter(null)}>
            {t('agents.side.all')}
            <span className="tabular-nums opacity-70">{matching.length}</span>
          </button>
          {STATE_GROUPS.filter((g) => counts[g.id] > 0 || filter === g.id).map((g) => (
            <button key={g.id} type="button" className={chip(filter === g.id, touch)} aria-pressed={filter === g.id} onClick={() => setFilter(filter === g.id ? null : g.id)} data-testid={`agents-filter-${g.id}`}>
              <StatusDot tone={g.tone} pulse={g.id === 'waiting' || g.id === 'running'} className="size-1.5" /> {g.label(t)}
              <span className="tabular-nums opacity-70">{counts[g.id]}</span>
            </button>
          ))}
        </div>
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
        ) : !groups.length && empty && !data?.agents.length ? (
          empty
        ) : !groups.length ? (
          <EmptyState compact icon={Bot} title={ql || topic || filter ? t('agents.side.noMatch') : t('agents.emptyTitle')} />
        ) : (
          groups.map((g, i) => (
            <Group
              key={g.id}
              project={g.id}
              label={g.label}
              index={i}
              layout={layout}
              among={shownProjects}
              head={
                <>
                  {g.emoji && <span aria-hidden>{g.emoji}</span>}
                  <span className="truncate">{g.label}</span>
                  <span className="font-normal tabular-nums">{g.agents.length}</span>
                </>
              }
            >
              {g.agents.map((a, j) => (
                <AgentRow key={a.path} agent={a} index={j} layout={layout} />
              ))}
            </Group>
          ))
        )}
      </div>
    </div>
  )
}

/** The look of the filter chips (the All / Running / Unread chips of the Sessions list). */
const chip = (on: boolean, touch: boolean) =>
  cn(
    'flex shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring',
    touch ? 'h-10 px-3 text-[13px]' : 'h-6 px-2.5 text-xs',
    on ? 'bg-foreground text-background' : 'bg-muted text-muted-foreground hover:text-foreground active:bg-accent',
  )

/** A project: its header (colour, name and count, "..." menu; dragged to move the project), then its agents. */
function Group({ project, label, index, layout, among, head, children }: { project: string; label: string; index: number; layout: AgentsLayoutApi; among: string[]; head: React.ReactNode; children: React.ReactNode }) {
  const t = useT()
  const dnd = useReorder({ kind: 'project', id: project, project, index }, (p) => layout.moveProject(p, project))
  return (
    <section {...dnd.target} aria-label={label} className={cn('relative mt-2 first:mt-0', dnd.dragging && 'opacity-50')}>
      <DropBar side={dnd.side} />
      <h3
        {...dnd.source}
        className={cn('group/head flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase', dnd.on && 'cursor-grab active:cursor-grabbing')}
        title={dnd.on ? t('agents.layout.dragProject') : undefined}
        data-testid="agents-group"
        data-project={project}
      >
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: OUTFIT[layout.colorOf(project)] }} data-testid="agents-project-dot" />
        {head}
        <ProjectMenu project={project} layout={layout} among={among} className="ml-auto opacity-0 group-hover/head:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 max-md:opacity-100" />
      </h3>
      {children}
    </section>
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

function AgentRow({ agent: a, index, layout }: { agent: Agent; index: number; layout: AgentsLayoutApi }) {
  const t = useT()
  const dnd = useReorder({ kind: 'agent', id: a.path, project: a.project, index }, (path) => layout.moveAgent(path, a))
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
      {...dnd.props}
      className={cn(
        'relative flex min-h-12 items-center gap-2.5 rounded-lg px-2 py-1.5 outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-14',
        active && 'bg-accent hover:bg-accent',
        dnd.dragging && 'opacity-50',
      )}
      data-testid="agents-row"
      data-state={state}
      data-path={a.path}
    >
      <DropBar side={dnd.side} />
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
          <Sensitive length={10}>{a.topic}</Sensitive>
        </span>
      </span>
      <span className="shrink-0 empty:hidden">
        <CountBadge count={unread} title={t('agents.list.unread', { count: unread })} />
      </span>
    </Link>
  )
}
