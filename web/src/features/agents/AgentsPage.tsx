// The overview of the Agents page (/agents with no agent selected, the right pane of AgentsLayout), in two views
// kept per browser (`mx-agents-overview`):
//   office  a little pixel office: one room per project (banner in the project colour), each agent a character at
//           its desk with a status bubble (working / new result / waiting for you / failed / asleep when off); the
//           character opens the agent, hovering it or its name tag shows its card (last result, cost, switch, Run)
//           in the room's side panel. "To read" first, as a row of characters.
//   list    one card per agent, "To read" first, then grouped by project.
// The agent's own page is /agents/<project>/<topic>/<name>.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { Armchair, LayoutList, Play, Plus, ShieldCheck } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentRoute, useAgents, useCrons, usePatchAgent, useWorkspace } from '@/lib/queries'
import type { Agent, Cron } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn, store } from '@/lib/utils'
import { Badge, Button, EmptyState, Segmented, Select, Sensitive, Skeleton, StatusDot, Switch, Tooltip, useMask } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { AgentAvatarIcon, DEFAULT_AVATAR, INK, SWATCH, projectColor } from './Avatar'
import { agentState, type AgentState } from './AgentsList'
import { TriggerChips, costLine, firstLine, reasonText, useAgentsOn, useRunNow } from './parts'

export type OverviewMode = 'office' | 'list'
const MODE_KEY = 'mx-agents-overview'

/** Office or list, kept per browser (the touch layout uses it too: list = the agents list). */
export function useOverviewMode(): [OverviewMode, (m: OverviewMode) => void] {
  const [m, setM] = React.useState<OverviewMode>(() => (store.get(MODE_KEY) === 'list' ? 'list' : 'office'))
  const set = React.useCallback((v: OverviewMode) => {
    store.set(MODE_KEY, v)
    setM(v)
  }, [])
  return [m, set]
}

export function OverviewModeToggle({ value, onChange }: { value: OverviewMode; onChange: (m: OverviewMode) => void }) {
  const t = useT()
  return (
    <Segmented
      size="sm"
      value={value}
      onChange={onChange}
      aria-label={t('agents.office.view')}
      options={[
        { value: 'office', label: <span className="max-lg:sr-only">{t('agents.office.office')}</span>, icon: <Armchair /> },
        { value: 'list', label: <span className="max-lg:sr-only">{t('agents.office.list')}</span>, icon: <LayoutList /> },
      ]}
    />
  )
}

/** "To read" first (a new result, waiting for an OK, working now). */
const hot = (a: Agent) => (a.thread_unread || 0) > 0 || (a.waiting || 0) > 0 || (a.running_now || 0) > 0

export function AgentsOverview({ onNew, mode, onMode, title }: { onNew: () => void; mode: OverviewMode; onMode: (m: OverviewMode) => void; title?: string }) {
  const t = useT()
  const on = useAgentsOn()
  const { data, isLoading, error, refetch } = useAgents(on !== false)
  const { data: crons } = useCrons()
  const { data: ws } = useWorkspace()
  const [project, setProject] = React.useState('_all')
  const mask = useMask()

  const agents = React.useMemo(() => data?.agents || [], [data])
  const cronsOf = React.useMemo(() => {
    const m = new Map<string, Cron[]>()
    for (const j of crons?.jobs || []) if (j.kind === 'claude' && /\/agents\/[^/]+$/.test(j.topic_path)) m.set(j.topic_path, [...(m.get(j.topic_path) || []), j])
    return m
  }, [crons])
  const projects = React.useMemo(() => [...new Set(agents.map((a) => a.project))], [agents])
  const shown = React.useMemo(() => agents.filter((a) => project === '_all' || a.project === project), [agents, project])
  const toRead = React.useMemo(() => shown.filter(hot), [shown])
  // Projects in the order of the workspace (the Sessions tree order); the office keeps every agent in its room.
  const byProject = React.useCallback(
    (list: Agent[]) => {
      const g = new Map<string, Agent[]>()
      for (const a of list) g.set(a.project, [...(g.get(a.project) || []), a])
      const order = (ws?.projects || []).map((p) => p.name)
      return [...g.entries()].sort(([x], [y]) => (order.indexOf(x) + 1 || 1e9) - (order.indexOf(y) + 1 || 1e9) || x.localeCompare(y))
    },
    [ws],
  )
  const groups = React.useMemo(() => byProject(shown.filter((a) => !hot(a))), [shown, byProject])
  const rooms = React.useMemo(() => byProject(shown), [shown, byProject])
  const emoji = (p: string) => ws?.projects.find((x) => x.name === p)?.emoji || ''

  return (
    <Page
      title={title || t('agents.side.overview')}
      description={t('agents.desc')}
      actions={
        <>
          <OverviewModeToggle value={mode} onChange={onMode} />
          {projects.length > 1 && (
            <Select
              value={project}
              onValueChange={setProject}
              aria-label={t('agents.filterProject')}
              className="w-40 max-sm:hidden"
              options={[{ value: '_all', label: t('agents.allProjects') }, ...projects.map((p) => ({ value: p, label: mask(p, 6) }))]}
            />
          )}
          <Button size="sm" onClick={onNew} data-testid="agent-new">
            <Plus /> <span className="max-[429px]:sr-only">{t('agents.new')}</span>
          </Button>
        </>
      }
    >
      {isLoading || on === undefined ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <EmptyState
          tone="error"
          title={t('agents.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : agents.length === 0 ? (
        <LonelyOffice onNew={onNew} />
      ) : mode === 'office' ? (
        <div className="grid gap-6" data-testid="agents-office">
          {toRead.length > 0 && (
            <section className="grid gap-3 rounded-xl border bg-card p-4" aria-label={t('agents.list.toRead')} data-testid="agents-to-read">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                {t('agents.list.toRead')} <Badge variant="default" className="h-4 px-1.5 text-[10px]">{toRead.length}</Badge>
              </h2>
              <ul className="flex flex-wrap gap-x-3 gap-y-4 pt-3">
                {toRead.map((a) => (
                  <li key={a.path}>
                    <Character agent={a} compact />
                  </li>
                ))}
              </ul>
            </section>
          )}
          {rooms.map(([p, list]) => (
            <Room key={p} project={p} emoji={emoji(p)} agents={list} cronsOf={cronsOf} />
          ))}
        </div>
      ) : (
        <div className="grid gap-8">
          {toRead.length > 0 && (
            <section className="grid gap-3" aria-label={t('agents.list.toRead')} data-testid="agents-to-read">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                {t('agents.list.toRead')} <Badge variant="default" className="h-4 px-1.5 text-[10px]">{toRead.length}</Badge>
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {toRead.map((a) => (
                  <li key={a.path}>
                    <AgentCard agent={a} crons={cronsOf.get(a.path) || []} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          {groups.map(([p, list]) => (
            <section key={p} className="grid gap-3" aria-label={p}>
              <h2 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
                {emoji(p) && <span aria-hidden>{emoji(p)}</span>}
                <Sensitive length={8}>{p}</Sensitive>
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {list.map((a) => (
                  <li key={a.path}>
                    <AgentCard agent={a} crons={cronsOf.get(a.path) || []} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Page>
  )
}

/** Checkered floor tiles drawn with theme colours (two shades of muted). */
const FLOOR: React.CSSProperties = {
  backgroundImage: 'conic-gradient(color-mix(in oklab, var(--color-muted) 70%, transparent) 25%, transparent 0 50%, color-mix(in oklab, var(--color-muted) 70%, transparent) 0 75%, transparent 0)',
  backgroundSize: '32px 32px',
}

/** One project = one room: a banner in its colour, the agents at their desks, the card of the one pointed at. */
function Room({ project, emoji, agents, cronsOf }: { project: string; emoji: string; agents: Agent[]; cronsOf: Map<string, Cron[]> }) {
  const t = useT()
  const color = projectColor(project)
  const sw = SWATCH[color]
  const [picked, setPicked] = React.useState<string | null>(null)
  // Shown before anything is pointed at: the most pressing agent, else the one that worked last.
  const sel = agents.find((a) => a.path === picked) || agents.find(hot) || [...agents].sort((a, b) => (b.last_run?.at || 0) - (a.last_run?.at || 0))[0]
  const working = agents.filter((a) => (a.running_now || 0) > 0).length
  return (
    <section className="overflow-hidden rounded-xl border bg-card" aria-label={project} data-testid="agents-room">
      <header className="flex min-h-11 items-center gap-2 px-4 py-2" style={{ background: sw.tile, color: INK, borderBottom: `4px solid ${sw.body}` }}>
        <Pennant color={sw.body} />
        {emoji && <span aria-hidden>{emoji}</span>}
        <h2 className="min-w-0 truncate text-sm font-semibold">
          <Sensitive length={8}>{project}</Sensitive>
        </h2>
        <span className="ml-auto shrink-0 text-xs font-medium tabular-nums opacity-75">
          {working > 0 ? t('agents.office.working', { count: working }) + ' · ' : ''}
          {t('agents.office.count', { count: agents.length })}
        </span>
      </header>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_20rem]">
        <ul className="flex flex-wrap content-start gap-x-4 gap-y-5 px-4 pt-9 pb-5 max-sm:justify-center max-sm:gap-x-2" style={FLOOR}>
          {agents.map((a) => (
            <li key={a.path} onPointerEnter={(e) => e.pointerType === 'mouse' && setPicked(a.path)} onFocus={() => setPicked(a.path)}>
              <Character agent={a} room={color} selected={a.path === sel?.path} onPick={() => setPicked(a.path)} />
            </li>
          ))}
        </ul>
        {sel && (
          <div className="border-t p-3 lg:border-t-0 lg:border-l" data-testid="agents-room-card">
            <AgentCard agent={sel} crons={cronsOf.get(sel.path) || []} flat />
          </div>
        )}
      </div>
    </section>
  )
}

/** A small pixel flag at the start of a room's banner. */
function Pennant({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 6 7" width={12} height={14} shapeRendering="crispEdges" aria-hidden className="shrink-0">
      <rect x="0" y="0" width="1" height="7" fill={INK} />
      <rect x="1" y="0" width="5" height="1" fill={INK} />
      <rect x="1" y="1" width="4" height="1" fill={color} />
      <rect x="1" y="2" width="3" height="1" fill={color} />
      <rect x="1" y="3" width="2" height="1" fill={color} />
      <rect x="5" y="1" width="1" height="1" fill={INK} />
      <rect x="4" y="2" width="1" height="1" fill={INK} />
      <rect x="3" y="3" width="1" height="1" fill={INK} />
      <rect x="1" y="4" width="2" height="1" fill={INK} />
    </svg>
  )
}

/** An agent as a character: its bubble above the head, its desk (office) or its tile (compact), its name tag. */
function Character({ agent: a, compact, room, selected, onPick }: { agent: Agent; compact?: boolean; room?: string; selected?: boolean; onPick?: () => void }) {
  const t = useT()
  const state = agentState(a)
  const off = state === 'off'
  const working = (a.running_now || 0) > 0
  const name = a.display_name
  return (
    <div className={cn('relative flex flex-col items-center', compact ? 'w-20' : 'w-24')} data-testid="agents-character" data-state={state}>
      <Bubble agent={a} state={state} />
      <Link
        to={agentRoute(a)}
        aria-label={t('agents.office.open', { name })}
        className="group/char relative flex flex-col items-center rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className={cn('block transition-transform duration-150 group-hover/char:-translate-y-0.5', working && 'mx-px-hop')}>
          <AgentAvatarIcon avatar={a.avatar} size={compact ? 60 : 80} tile={!!compact} mood={off ? 'sleep' : 'idle'} animate={!off} className={cn(compact && 'rounded-md')} />
        </span>
        {!compact && <Desk color={room || DEFAULT_AVATAR.color} running={working} className="-mt-4" />}
      </Link>
      {onPick ? (
        <button
          type="button"
          onClick={onPick}
          aria-pressed={selected}
          aria-label={t('agents.office.details', { name })}
          className={cn(
            'relative mt-1.5 max-w-full truncate rounded-[4px] border-2 px-1.5 py-px text-xs font-medium shadow-[2px_2px_0_0_var(--color-border)] outline-none focus-visible:ring-2 focus-visible:ring-ring max-md:py-1',
            selected ? 'border-foreground bg-foreground text-background' : 'border-border bg-card hover:border-foreground/50',
            off && !selected && 'text-muted-foreground',
          )}
          data-testid="agents-nametag"
        >
          <Sensitive length={8}>{name}</Sensitive>
        </button>
      ) : (
        <span className={cn('mt-1.5 block max-w-full truncate text-center text-xs font-medium', off && 'text-muted-foreground')}>
          <Sensitive length={8}>{name}</Sensitive>
        </span>
      )}
    </div>
  )
}

/** What floats above the head: working (dots), waiting for an OK (shield), a failed run (!), new results (count),
 *  asleep when off (z). Nothing when idle. */
function Bubble({ agent: a, state: s0 }: { agent: Agent; state: AgentState }) {
  const t = useT()
  // Working shows before a new result (agentState puts results first).
  const state: AgentState = s0 === 'unread' && (a.running_now || 0) > 0 ? 'running' : s0
  const failed = a.last_run?.kind === 'result' && a.last_run.ok === false
  const box = 'absolute -top-6 right-0 z-10 flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-[4px] border-2 border-foreground px-1 text-xs leading-none font-bold shadow-[2px_2px_0_0_var(--color-foreground)] mx-pop'
  const tail = (cls: string) => <span aria-hidden className={cn('absolute -bottom-[5px] left-1 size-2 rotate-45 border-r-2 border-b-2 border-foreground', cls)} />
  if (state === 'off')
    return (
      <span role="img" aria-label={t('agents.side.state.off')} className="absolute -top-4 right-2 z-10 font-mono text-sm font-bold text-muted-foreground">
        <span className="mx-px-zzz inline-block">z</span>
        <span className="mx-px-zzz inline-block text-xs [animation-delay:1.3s]">z</span>
      </span>
    )
  if (state === 'waiting')
    return (
      <span role="img" aria-label={t('agents.list.waiting')} className={cn(box, 'bg-card text-warning')}>
        <ShieldCheck className="size-3.5" strokeWidth={2.5} />
        {tail('bg-card')}
      </span>
    )
  if (state === 'running')
    return (
      <span role="img" aria-label={t('agents.list.working')} className={cn(box, 'mx-px-dots bg-card px-1.5')}>
        <i className="size-1 bg-foreground" />
        <i className="size-1 bg-foreground" />
        <i className="size-1 bg-foreground" />
        {tail('bg-card')}
      </span>
    )
  if (state === 'unread' || state === 'failed') {
    // A new result that is a failure is red too.
    const n = a.thread_unread || 0
    const bad = failed
    return (
      <span
        role="img"
        aria-label={bad ? t('agents.side.state.failed') : t('agents.list.unread', { count: n })}
        className={cn(box, bad ? 'bg-destructive text-destructive-foreground' : 'bg-primary text-primary-foreground')}
      >
        !{n > 1 && <span className="tabular-nums">{n}</span>}
        {tail(bad ? 'bg-destructive' : 'bg-primary')}
      </span>
    )
  }
  return null
}

/** The desk in front of a character, in pixels and in the pastel shades of its room's colour (the shirt in the
 *  project colour stands out on it), with a mug and a laptop seen from behind (its screen glows while it works). */
function Desk({ color, running, className }: { color: string; running: boolean; className?: string }) {
  const sw = SWATCH[color] || SWATCH.slate
  const px = (x: number, y: number, w: number, h: number, fill: string) => <rect x={x} y={y} width={w} height={h} fill={fill} />
  return (
    <svg viewBox="0 0 24 7" width={96} height={28} shapeRendering="crispEdges" aria-hidden className={cn('shrink-0 overflow-visible', className)}>
      {/* laptop seen from behind (its screen glows while it works) and a mug */}
      {running && px(16, -1, 6, 1, sw.light)}
      {px(16, 0, 6, 2, sw.shade)}
      {px(18, 0, 2, 1, sw.tile)}
      {px(2, 0, 3, 2, '#ffffff')}
      {px(2, 0, 3, 1, sw.shade)}
      {px(5, 1, 1, 1, sw.shade)}
      {/* top, then front with its drawer */}
      {px(0, 2, 24, 1, sw.shade)}
      {px(0, 3, 24, 1, sw.tile2)}
      {px(1, 4, 22, 3, sw.tile)}
      {px(0, 4, 1, 3, sw.shade)}
      {px(23, 4, 1, 3, sw.shade)}
      {px(1, 4, 22, 1, sw.tile2)}
      {px(10, 5, 4, 1, sw.shade)}
    </svg>
  )
}

/** The empty page: one lonely character waiting at its desk, and the way to create the first agent. */
function LonelyOffice({ onNew }: { onNew: () => void }) {
  const t = useT()
  return (
    <div className="grid justify-items-center gap-6 py-10 text-center" data-testid="agents-empty">
      <div className="relative flex w-56 flex-col items-center rounded-xl border px-6 pt-10 pb-4" style={FLOOR}>
        <span className="absolute top-3 right-10 z-10 flex h-6 items-center gap-0.5 rounded-[4px] border-2 border-foreground bg-card px-1.5 text-xs font-bold shadow-[2px_2px_0_0_var(--color-foreground)]">?</span>
        <AgentAvatarIcon avatar={{ ...DEFAULT_AVATAR, eyes: 'wide', mouth: 'open', hat: 'cap', color: 'blue', hair: 'none' }} tile={false} size={80} animate />
        <Desk color="blue" running={false} className="-mt-4" />
      </div>
      <div className="grid max-w-lg gap-2">
        <h2 className="text-base font-semibold">{t('agents.emptyTitle')}</h2>
        <p className="text-sm text-muted-foreground">{t('agents.emptyDesc')}</p>
        <p className="text-sm text-muted-foreground">{t('agents.emptyDesc2')}</p>
      </div>
      <Button onClick={onNew}>
        <Plus /> {t('agents.create')}
      </Button>
    </div>
  )
}

/** One agent as a card: face, name, switch, what it did last, triggers, cost, Run. `flat` = inside a room's panel. */
function AgentCard({ agent: a, crons, flat }: { agent: Agent; crons: Cron[]; flat?: boolean }) {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  const run = useRunNow()
  const open = () => navigate(agentRoute(a))
  const last = a.last_run
  const running = (a.running_now || a.running || 0) > 0
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open())}
      className={cn(
        'flex h-full cursor-pointer flex-col gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        flat && 'border-transparent p-2 hover:border-transparent',
        !a.enabled && 'opacity-75',
      )}
      data-testid="agent-card"
    >
      <div className="flex items-start gap-3">
        <AgentAvatarIcon avatar={a.avatar} size={flat ? 40 : 44} className="rounded-md" />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate font-medium">
              <Sensitive length={8}>{a.display_name}</Sensitive>
            </span>
            {(a.thread_unread || 0) > 0 && <span className="size-2 shrink-0 rounded-full bg-primary" title={t('agents.list.unread', { count: a.thread_unread || 0 })} aria-label={t('agents.list.unread', { count: a.thread_unread || 0 })} />}
          </div>
          <span className="truncate text-xs text-muted-foreground">
            <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
          </span>
        </div>
        <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} className="flex items-center">
          <Switch checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} aria-label={a.enabled ? t('agents.switchOff') : t('agents.switchOn')} data-testid="agent-enabled" />
        </div>
      </div>
      <LastLine agent={a} running={running} />
      <TriggerChips agent={a} crons={crons} />
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">
          {last?.kind === 'result' && last.ok !== false ? null : !last ? (
            t('agents.neverRun')
          ) : last.kind === 'skip' ? (
            <span className="text-warning">{t('agents.lastSkipped', { when: fmtRelative(last.at, lang), reason: reasonText(t, last.reason) || last.text })}</span>
          ) : (
            <span className={last.ok === false ? 'text-destructive' : undefined}>
              {t(last.ok === false ? 'agents.lastFailed' : 'agents.lastRun', { when: fmtRelative(last.at, lang) })}
            </span>
          )}
        </span>
        <span className="tabular-nums">
          <Sensitive length={6}>{costLine(t, a)}</Sensitive>
        </span>
        <Tooltip content={a.enabled ? t('agents.run.now') : t('agents.reason.disabled')}>
          <span onClick={(e) => e.stopPropagation()}>
            <Button size="sm" variant="outline" className="h-7" disabled={!a.enabled} loading={run.pending && run.vars?.path === a.path} onClick={() => run.go(a)} data-testid="agent-run">
              <Play /> {t('agents.run.button')}
            </Button>
          </span>
        </Tooltip>
      </div>
    </div>
  )
}

/** What the card says first: working now, waiting for an OK, its last result, or (never run) its role. */
function LastLine({ agent: a, running }: { agent: Agent; running: boolean }) {
  const t = useT()
  const lang = useLang()
  const last = a.last_run
  const box = 'grid min-h-14 content-start gap-0.5 rounded-lg bg-muted/50 px-3 py-2 text-sm'
  if ((a.waiting || 0) > 0)
    return (
      <div className={cn(box, 'bg-warning/10')} data-testid="agent-card-waiting">
        <span className="flex items-center gap-1.5 font-medium text-warning">
          <ShieldCheck className="size-3.5" /> {t('agents.list.waiting')}
        </span>
      </div>
    )
  if (running)
    return (
      <div className={box}>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <StatusDot tone="running" pulse className="size-2" /> {t('agents.list.working')}
        </span>
      </div>
    )
  if (last?.kind === 'result' && last.text)
    return (
      <div className={box}>
        <span className="text-[11px] text-muted-foreground">{fmtRelative(last.at, lang)}</span>
        <span className={cn('line-clamp-2', last.ok === false && 'text-destructive')}>
          <Sensitive block>{firstLine(last.text.replace(/^#+\s*/, ''))}</Sensitive>
        </span>
      </div>
    )
  return (
    <p className="line-clamp-2 min-h-10 text-sm text-muted-foreground">
      {a.description ? <Sensitive block>{firstLine(a.description)}</Sensitive> : <span className="italic">{t('agents.noRole')}</span>}
    </p>
  )
}
