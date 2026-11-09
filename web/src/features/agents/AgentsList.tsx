// The left column of the Agents page (like the contact list of a chat app): every agent with its face, its name, its
// topic, a status dot and its unread count, always grouped by project (order and colour of layout.tsx: drag a project
// header or an agent to move it, the "..." of a project for Move up / down and its colour). On top: `nav` (OfficeLink),
// then the state filter (All / waiting for you / to read / running / active / off, with counts; empty states hidden)
// and the ?topic= chip. No search field (Ctrl K finds agents and groups); New agent / New group sit at the top right
// of the Office (AgentsPage.tsx), and of the list's own header on a phone (AgentsLayout.tsx).
// The groups of a project (agent_rooms: the owner talks to several of its agents) come first in its section: the
// chips To read / Running keep the unread / busy ones, the other chips hide them.
// On a phone it is the whole page at /agents (an agent then opens full screen); on a desktop, the page's left column.
import * as React from 'react'
import { Link, useLocation, useMatch, useSearchParams } from 'react-router'
import { Bot, Building2, TriangleAlert, UsersRound, X } from 'lucide-react'
import { useT, type TFn } from '@/i18n'
import { agentRoute, groupRoute, useAgentGroups, useAgents, useWorkspace } from '@/lib/queries'
import type { Agent, AgentGroup } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button, CountBadge, EmptyState, Sensitive, Skeleton, StatusDot, useMask, type DotTone } from '@/components/ui'
import { useCompact } from '@/stores/media'
import { AgentAvatarIcon, OUTFIT } from './Avatar'
import { DropBar, ProjectMenu, useAgentsLayout, useReorder, type AgentsLayoutApi } from './layout'
import { SilentMark, useAgentMenu } from './AgentMenu'

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
/** The way back to the Office (every agent at its desk), whichever agent or run is open: a nav entry of its own, set
 *  apart from the search and New agent above it. */
export function OfficeLink() {
  const t = useT()
  const touch = useCompact()
  const { pathname } = useLocation()
  const office = !touch && /^\/agents(\/office)?\/?$/.test(pathname)
  return (
    <div className="shrink-0 border-y px-2 py-1.5">
      <Link
        to={touch ? '/agents/office' : '/agents'}
        aria-current={office ? 'page' : undefined}
        className={cn(
          'flex items-center gap-2.5 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
          touch ? 'h-11' : 'h-9',
          office && 'bg-accent text-foreground',
        )}
        data-testid="agents-office"
      >
        <Building2 className="size-4" />
        {t('agents.side.office')}
      </Link>
    </div>
  )
}

export function AgentsList({ empty, nav, className }: { empty?: React.ReactNode; nav?: React.ReactNode; className?: string }) {
  const t = useT()
  const mask = useMask()
  const touch = useCompact()
  const { data, isLoading, error, refetch } = useAgents()
  const { data: ws } = useWorkspace()
  const { data: allGroups } = useAgentGroups()
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = React.useState<StateFilter | null>(null)
  // ?topic=<project>/<topic>: only the agents of that topic (the link from a topic's menu in Sessions).
  const onAgents = useLocation().pathname.startsWith('/agents')
  const topic = (onAgents && params.get('topic')) || ''

  // The topic chip narrows first; the state chips count what is left.
  const matching = React.useMemo(() => {
    const all = data?.agents || []
    return all
      .filter((a) => !topic || `${a.project}/${a.topic}` === topic)
      .sort(byActivity)
  }, [data, topic])
  const counts = React.useMemo(() => {
    const c = {} as Record<StateFilter, number>
    for (const g of STATE_GROUPS) c[g.id] = matching.filter((a) => g.has(agentState(a))).length
    return c
  }, [matching])
  const shown = React.useMemo(() => {
    const g = STATE_GROUPS.find((x) => x.id === filter)
    return g ? matching.filter((a) => g.has(agentState(a))) : matching
  }, [matching, filter])

  // The groups follow the same narrowing: the topic (one of their members is in it), then the chips.
  const rooms = React.useMemo(() => {
    const g = filter === null || filter === 'unread' || filter === 'running' ? allGroups || [] : []
    return g
      .filter((x) => !topic || x.members.some((m) => m.path.startsWith(`projects/${topic.replace('/', '/topics/')}/`)))
      .filter((x) => (filter === 'unread' ? x.unread > 0 : filter === 'running' ? x.busy : true))
      .sort((a, b) => (b.last_at || b.created) - (a.last_at || a.created))
  }, [allGroups, filter, topic])

  const layout = useAgentsLayout()
  const groups = React.useMemo(() => {
    const byProject = layout.group(shown)
    // A project whose agents are all filtered out still shows its groups (in the layout order, else at the end).
    const extra = [...new Set(rooms.map((r) => r.project))].filter((p) => !byProject.some((x) => x.project === p))
    const rank = (p: string) => (layout.projects.includes(p) ? layout.projects.indexOf(p) : 1e9)
    const all = [...byProject, ...extra.map((p) => ({ project: p, agents: [] as Agent[] }))].sort((a, b) => rank(a.project) - rank(b.project))
    return all.map(({ project: p, agents }) => ({
      id: p,
      label: mask(p, 8),
      emoji: ws?.projects.find((x) => x.name === p)?.emoji || '',
      agents,
      rooms: rooms.filter((r) => r.project === p),
    }))
  }, [shown, rooms, ws, mask, layout])
  const shownProjects = groups.map((g) => g.id)

  return (
    // Short screen (a phone sideways): the Office entry and the chips scroll away with the list, which
    // would keep about two rows otherwise.
    <div className={cn('flex min-h-0 flex-col [@media(max-height:500px)]:overflow-y-auto', className)} data-testid="agents-list">
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
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 [@media(max-height:500px)]:flex-none [@media(max-height:500px)]:overflow-visible" role="list">
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
          <EmptyState compact icon={Bot} title={topic || filter ? t('agents.side.noMatch') : t('agents.emptyTitle')} />
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
              {g.rooms.map((r) => (
                <GroupRow key={r.path} group={r} />
              ))}
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

/** A group of the project: its emoji, its name, its members' faces (stacked), "X is writing…" while one speaks. */
function GroupRow({ group: g }: { group: AgentGroup }) {
  const t = useT()
  const location = useLocation()
  const to = groupRoute(g)
  const active = !!useMatch({ path: to })
  const speaker = g.members.find((m) => m.path === g.speaking)
  const unread = g.unread > 0
  return (
    <Link
      role="listitem"
      to={{ pathname: to, search: location.pathname.startsWith('/agents') ? location.search : '' }}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex min-h-12 items-center gap-2.5 rounded-lg px-2 py-1.5 outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-14',
        active && 'bg-accent hover:bg-accent',
      )}
      data-testid="groups-row"
      data-path={g.path}
    >
      <span className="relative shrink-0">
        <GroupFace group={g} size={32} />
        {g.busy && (
          <span className="absolute -right-0.5 -bottom-0.5 grid size-3 place-items-center rounded-full bg-background">
            <StatusDot tone="running" pulse className="size-2" label={t('groups.busy')} />
          </span>
        )}
      </span>
      <span className="grid min-w-0 flex-1">
        <span className={cn('truncate text-sm', unread ? 'font-semibold' : 'font-medium')}>
          <Sensitive length={8}>{g.display_name}</Sensitive>
        </span>
        {speaker ? (
          <span className="truncate text-xs text-primary">{t('groups.writing', { name: speaker.display_name })}</span>
        ) : (
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <MemberStack members={g.members} />
            <span className="truncate">{t('groups.members', { count: g.members.length })}</span>
          </span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-1 empty:hidden">
        <CountBadge count={g.unread} title={t('groups.unread')} />
      </span>
    </Link>
  )
}

/** The face of a group: its emoji on a tile (the size of an agent's face), else its members' initial look. */
export function GroupFace({ group: g, size = 32 }: { group: Pick<AgentGroup, 'emoji' | 'display_name'>; size?: number }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-lg bg-muted" style={{ width: size, height: size, fontSize: Math.round(size * 0.55) }} aria-hidden>
      {g.emoji || <UsersRound className="size-1/2 text-muted-foreground" />}
    </span>
  )
}

/** The faces of the members, overlapping (4 at most, then nothing: the count says the rest). */
export function MemberStack({ members, size = 16 }: { members: AgentGroup['members']; size?: number }) {
  return (
    <span className="flex shrink-0 -space-x-1" aria-hidden>
      {members.slice(0, 4).map((m) => (
        <span key={m.path} className={cn('rounded-[5px] bg-background ring-1 ring-background', (m.paused || !m.exists) && 'opacity-50')}>
          <AgentAvatarIcon avatar={m.avatar} size={size} />
        </span>
      ))}
    </span>
  )
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
  const ctx = useAgentMenu(a)
  return (
    <Link
      role="listitem"
      to={{ pathname: to, search: location.pathname.startsWith('/agents') ? location.search : '' }}
      aria-current={active ? 'page' : undefined}
      {...dnd.props}
      {...ctx.props}
      className={cn(
        'relative flex min-h-12 items-center gap-2.5 rounded-lg px-2 py-1.5 outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-14',
        active && 'bg-accent hover:bg-accent',
        dnd.dragging && 'opacity-50',
      )}
      data-testid="agents-row"
      data-rail-agent
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
        <span className="flex min-w-0 items-center gap-1">
          <span className={cn('truncate text-sm', unread > 0 || state === 'waiting' ? 'font-semibold' : 'font-medium', state === 'off' && 'text-muted-foreground')}>
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          <SilentMark agent={a} />
        </span>
        <span className="truncate text-xs text-muted-foreground">
          <Sensitive length={10}>{a.topic}</Sensitive>
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 empty:hidden">
        {!!a.alerts && (
          <span
            className="inline-flex h-5 items-center gap-0.5 rounded-full bg-destructive/12 px-1.5 text-[11px] font-semibold text-destructive tabular-nums"
            title={t('agents.list.alerts', { count: a.alerts })}
            aria-label={t('agents.list.alerts', { count: a.alerts })}
            data-testid="agents-row-alerts"
          >
            <TriangleAlert className="size-3" strokeWidth={2.5} />
            {a.alerts}
          </span>
        )}
        <CountBadge count={unread} title={t('agents.list.unread', { count: unread })} />
      </span>
      {ctx.menu}
    </Link>
  )
}
