// The overview of the Agents page, the Office (/agents with no agent selected, the right pane of AgentsLayout on a
// computer; /agents/office on a phone). Two views, picked at the top right and kept per browser: Gamified (a
// pixel-art office, OfficeGame.tsx) and Classic, below:
// one section per project (dot in the project colour, name, count, "..." menu, like the lanes of Tasks; order, colours
// and drag and drop of projects and agents: layout.tsx), each agent a card with
// its character sitting behind a small desk, its name and one status line in words. A small bubble above the head
// only when something matters (working, new results, waiting for an OK, failed). The whole card opens the agent;
// Run and the on/off switch show on hover or focus (always on touch screens).
// The agent's own page is /agents/<project>/<topic>/<name>; on a phone /agents is the list (AgentsList).
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { ArrowLeft, Gamepad2, LayoutGrid, Play, Plus, ShieldCheck } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentRoute, useAgents, usePatchAgent } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { cn, store } from '@/lib/utils'
import { useCompact } from '@/stores/media'
import { Button, EmptyState, Segmented, Sensitive, Skeleton, StatusDot, Switch, Tooltip } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { AgentAvatarIcon, DEFAULT_AVATAR, OUTFIT } from './Avatar'
import { statusOf, useAgentsOn, useRunNow, type Status } from './parts'
import { QuickCreate, type CreateStart } from './CreateAgent'
import { OfficeGame } from './OfficeGame'
import { DropBar, ProjectMenu, useAgentsLayout, useReorder, type AgentsLayoutApi } from './layout'

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3'

export type OfficeView = 'classic' | 'game'
const VIEW_KEY = 'mx-agents-office-view'

/** The view of the Office, kept per browser (Classic by default). */
function useOfficeView(): [OfficeView, (v: OfficeView) => void] {
  const [v, setV] = React.useState<OfficeView>(() => (store.get(VIEW_KEY) === 'game' ? 'game' : 'classic'))
  const set = React.useCallback((x: OfficeView) => {
    store.set(VIEW_KEY, x)
    setV(x)
  }, [])
  return [v, set]
}

export function AgentsOverview({ onNew, onStart }: { onNew: () => void; onStart: (s: CreateStart) => void }) {
  const t = useT()
  const on = useAgentsOn()
  const { data, isLoading, error, refetch } = useAgents(on !== false)
  const agents = React.useMemo(() => data?.agents || [], [data])
  const [view, setView] = useOfficeView()
  const touch = useCompact()
  // Projects and agents in the order of the layout (picked by hand, else workspace order / topic then name).
  const layout = useAgentsLayout()
  const groups = React.useMemo(() => layout.group(agents), [agents, layout])

  return (
    <Page
      title={t('agents.side.office')}
      description={t('agents.desc')}
      width={view === 'game' ? 'wide' : 'default'}
      leading={
        touch ? (
          <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.back')} className="-ml-1">
            <Link to="/agents">
              <ArrowLeft />
            </Link>
          </Button>
        ) : undefined
      }
      actions={
        <>
          {agents.length > 0 && (
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              aria-label={t('agents.office.view')}
              options={[
                { value: 'classic', icon: <LayoutGrid />, label: <span className="max-sm:sr-only">{t('agents.office.classic')}</span> },
                { value: 'game', icon: <Gamepad2 />, label: <span className="max-sm:sr-only">{t('agents.office.game')}</span> },
              ]}
            />
          )}
          <Button size="sm" onClick={onNew} data-testid="agent-new">
            <Plus /> <span className="max-[429px]:sr-only">{t('agents.new')}</span>
          </Button>
        </>
      }
    >
      {isLoading || on === undefined ? (
        <div className={GRID}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[11.5rem] rounded-xl" />
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
        <AgentsEmpty onStart={onStart} />
      ) : view === 'game' ? (
        <OfficeGame groups={groups} layout={layout} onStart={onStart} />
      ) : (
        <div className="grid gap-8" data-testid="agents-overview">
          {groups.map(({ project: p, agents: list }, i) => (
            <ProjectSection key={p} project={p} count={list.length} index={i} layout={layout}>
              <ul className={GRID}>
                {list.map((a, j) => (
                  <li key={a.path}>
                    <AgentTile agent={a} index={j} layout={layout} />
                  </li>
                ))}
              </ul>
            </ProjectSection>
          ))}
        </div>
      )}
    </Page>
  )
}

/** A project of the Classic view: its header (colour, name, count, "..."), dragged to move the whole section. */
function ProjectSection({ project: p, count: n, index, layout, children }: { project: string; count: number; index: number; layout: AgentsLayoutApi; children: React.ReactNode }) {
  const t = useT()
  const dnd = useReorder({ kind: 'project', id: p, project: p, index }, (x) => layout.moveProject(x, p))
  return (
    <section {...dnd.target} className={cn('relative grid gap-3 rounded-xl', dnd.dragging && 'opacity-50')} aria-label={p} data-testid="agents-project" data-project={p}>
      <DropBar side={dnd.side} className="inset-x-0 h-1" />
      <h2 {...dnd.source} className={cn('group/head flex items-center gap-2 px-0.5 text-[13px] font-semibold', dnd.on && 'cursor-grab active:cursor-grabbing')} title={dnd.on ? t('agents.layout.dragProject') : undefined} data-testid="agents-project-head">
        <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: OUTFIT[layout.colorOf(p)] }} data-testid="agents-project-dot" />
        <Sensitive length={8}>{p}</Sensitive>
        <span className="text-xs font-normal text-muted-foreground tabular-nums">{t('agents.overview.count', { count: n })}</span>
        <ProjectMenu project={p} layout={layout} among={layout.projects} className="opacity-0 group-hover/head:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 max-md:opacity-100" />
      </h2>
      {children}
    </section>
  )
}

/** An agent: its character behind its desk, its name, its status; Run and the switch on hover. */
function AgentTile({ agent: a, index, layout }: { agent: Agent; index: number; layout: AgentsLayoutApi }) {
  const t = useT()
  const dnd = useReorder({ kind: 'agent', id: a.path, project: a.project, index }, (path) => layout.moveAgent(path, a))
  const lang = useLang()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  const run = useRunNow()
  const s = statusOf(a, t, lang)
  const open = () => navigate(agentRoute(a))
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  return (
    <div
      role="link"
      tabIndex={0}
      aria-label={t('agents.overview.open', { name: a.display_name })}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open())}
      {...dnd.props}
      className={cn(
        'group/tile relative grid cursor-pointer justify-items-center gap-3 rounded-xl border bg-card px-3 pt-5 pb-4 text-center transition-colors hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        dnd.dragging && 'opacity-50',
        dnd.side && 'border-primary',
      )}
      data-testid="agent-card"
      data-state={s.id}
      data-path={a.path}
    >
      <DropBar side={dnd.side} vertical={false} />
      <AtDesk agent={a} status={s} />
      <div className="grid w-full min-w-0 gap-0.5">
        <span className={cn('truncate text-sm font-medium', !a.enabled && 'text-muted-foreground')}>
          <Sensitive length={8}>{a.display_name}</Sensitive>
        </span>
        <span className={cn('flex min-w-0 items-center justify-center gap-1.5 text-xs', s.id === 'failed' ? 'text-destructive' : s.id === 'waiting' ? 'text-warning' : 'text-muted-foreground')} data-testid="agent-card-status">
          <StatusDot tone={s.tone} pulse={s.pulse} className="size-1.5" />
          <span className="truncate">{s.text}</span>
        </span>
      </div>
      {/* Hover / focus (always on touch screens): the switch on the left, Run on the right. */}
      <div className="absolute inset-x-2 top-2 flex items-center justify-between opacity-0 transition-opacity group-focus-within/tile:opacity-100 group-hover/tile:opacity-100 max-md:opacity-100" onClick={stop} onKeyDown={stop}>
        <Tooltip content={a.enabled ? t('agents.switchOff') : t('agents.switchOn')}>
          <span className="flex">
            <Switch checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} aria-label={a.enabled ? t('agents.switchOff') : t('agents.switchOn')} className="scale-90" data-testid="agent-enabled" />
          </span>
        </Tooltip>
        <Tooltip content={a.enabled ? t('agents.run.now') : t('agents.reason.disabled')}>
          <span className="flex">
            <Button size="icon-sm" variant="ghost" disabled={!a.enabled} loading={run.pending && run.vars?.path === a.path} onClick={() => run.go(a)} aria-label={t('agents.run.now')} data-testid="agent-run">
              <Play />
            </Button>
          </span>
        </Tooltip>
      </div>
    </div>
  )
}

/** The character sitting behind a small flat desk (theme greys), its laptop on the side lit while it works. */
function AtDesk({ agent, status }: { agent?: Agent; status?: Status }) {
  const working = status?.id === 'running'
  const off = status?.id === 'off'
  return (
    <div className="relative flex h-[76px] w-32 items-end justify-center" aria-hidden>
      <span className="relative mb-1">
        <AgentAvatarIcon avatar={agent?.avatar || { ...DEFAULT_AVATAR, face: 'happy' }} size={64} tile={false} mood={off ? 'sleep' : 'idle'} animate={!off} />
        {agent && status && <Bubble agent={agent} status={status} />}
      </span>
      <span className={cn('absolute right-3 bottom-3 h-4 w-6 rounded-t-[3px] bg-muted-foreground/25 transition-colors', working && 'bg-primary/45')} />
      <span className="absolute inset-x-0 bottom-0 grid">
        <span className="h-1 rounded-full bg-foreground/15" />
        <span className="mx-2 h-2.5 rounded-b-md bg-muted" />
      </span>
    </div>
  )
}

/** A small bubble above the head for the states that matter; nothing otherwise. */
function Bubble({ agent: a, status: s }: { agent: Agent; status: Status }) {
  const box = 'absolute -top-1 -right-3 flex h-5 min-w-5 items-center justify-center gap-0.5 rounded-full border bg-popover px-1.5 text-[11px] leading-none font-semibold shadow-xs'
  if (s.id === 'running')
    return (
      <span className={cn(box, 'mx-px-dots')}>
        <i className="size-1 rounded-full bg-muted-foreground" />
        <i className="size-1 rounded-full bg-muted-foreground" />
        <i className="size-1 rounded-full bg-muted-foreground" />
      </span>
    )
  if (s.id === 'waiting')
    return (
      <span className={cn(box, 'text-warning')}>
        <ShieldCheck className="size-3" strokeWidth={2.5} />
      </span>
    )
  if (s.id === 'unread') return <span className={cn(box, 'text-success tabular-nums')}>{a.thread_unread}</span>
  if (s.id === 'failed') return <span className={cn(box, 'text-destructive')}>!</span>
  return null
}

/** No agent yet: one character waiting at its desk, what an agent is in a sentence, then the same ways in as the
 *  creation sheet - where, then With Claude (a session in Sessions prepares it), by hand, a ready-made agent or a file. */
export function AgentsEmpty({ onStart }: { onStart: (s: CreateStart) => void }) {
  const t = useT()
  return (
    <div className="mx-auto grid w-full max-w-2xl gap-6 px-3 py-10 max-md:py-6" data-testid="agents-empty">
      <div className="grid justify-items-center gap-4 text-center">
        <AtDesk />
        <div className="grid max-w-lg gap-1.5">
          <h2 className="text-base font-semibold tracking-tight">{t('agents.emptyTitle')}</h2>
          <p className="text-sm text-muted-foreground">{t('agents.emptyDesc')}</p>
        </div>
      </div>
      <QuickCreate
        onManual={(topic) => onStart({ manual: true, topic })}
        onImport={(topic) => onStart({ importing: true, topic })}
        onTemplate={(template, topic) => onStart({ template, topic })}
        onDone={() => {}}
      />
    </div>
  )
}
