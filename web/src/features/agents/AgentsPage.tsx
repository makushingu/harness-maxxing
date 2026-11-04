// The overview of the Agents page (/agents with no agent selected, the right pane of AgentsLayout on a computer):
// one section per project (dot in the project colour, name, count, like the lanes of Tasks), each agent a card with
// its character sitting behind a small desk, its name and one status line in words. A small bubble above the head
// only when something matters (working, new results, waiting for an OK, failed). The whole card opens the agent;
// Run and the on/off switch show on hover or focus (always on touch screens).
// The agent's own page is /agents/<project>/<topic>/<name>; on a phone /agents is the list (AgentsList).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Play, Plus, ShieldCheck } from 'lucide-react'
import { useLang, useT, type TFn } from '@/i18n'
import { agentRoute, useAgents, usePatchAgent, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Button, EmptyState, Sensitive, Skeleton, StatusDot, Switch, Tooltip, type DotTone } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { AgentAvatarIcon, DEFAULT_AVATAR, OUTFIT, projectColor } from './Avatar'
import { useAgentsOn, useRunNow } from './parts'

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3'

export function AgentsOverview({ onNew }: { onNew: () => void }) {
  const t = useT()
  const on = useAgentsOn()
  const { data, isLoading, error, refetch } = useAgents(on !== false)
  const { data: ws } = useWorkspace()
  const agents = React.useMemo(() => data?.agents || [], [data])
  // Projects in the order of the workspace (the Sessions tree order), agents by topic then name.
  const groups = React.useMemo(() => {
    const g = new Map<string, Agent[]>()
    for (const a of [...agents].sort((x, y) => x.topic.localeCompare(y.topic) || x.display_name.localeCompare(y.display_name))) g.set(a.project, [...(g.get(a.project) || []), a])
    const order = (ws?.projects || []).map((p) => p.name)
    return [...g.entries()].sort(([x], [y]) => (order.indexOf(x) + 1 || 1e9) - (order.indexOf(y) + 1 || 1e9) || x.localeCompare(y))
  }, [agents, ws])

  return (
    <Page
      title={t('agents.side.overview')}
      description={t('agents.desc')}
      actions={
        <Button size="sm" onClick={onNew} data-testid="agent-new">
          <Plus /> <span className="max-[429px]:sr-only">{t('agents.new')}</span>
        </Button>
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
        <EmptyOverview onNew={onNew} />
      ) : (
        <div className="grid gap-8" data-testid="agents-overview">
          {groups.map(([p, list]) => (
            <section key={p} className="grid gap-3" aria-label={p} data-testid="agents-project">
              <h2 className="flex items-center gap-2 px-0.5 text-[13px] font-semibold">
                <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: OUTFIT[projectColor(p)] }} />
                <Sensitive length={8}>{p}</Sensitive>
                <span className="text-xs font-normal text-muted-foreground tabular-nums">{t('agents.overview.count', { count: list.length })}</span>
              </h2>
              <ul className={GRID}>
                {list.map((a) => (
                  <li key={a.path}>
                    <AgentTile agent={a} />
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

type Status = { id: 'waiting' | 'running' | 'unread' | 'failed' | 'off' | 'idle'; tone: DotTone; pulse?: boolean; text: string }

/** One status per agent in words, the most pressing first (working beats new results: it is live). */
function statusOf(a: Agent, t: TFn, lang: string): Status {
  const last = a.last_run
  if ((a.waiting || 0) > 0) return { id: 'waiting', tone: 'warn', pulse: true, text: t('agents.list.waiting') }
  if ((a.running_now || 0) > 0) return { id: 'running', tone: 'running', pulse: true, text: t('agents.list.working') }
  if ((a.thread_unread || 0) > 0) return { id: 'unread', tone: 'unread', text: t('agents.list.unread', { count: a.thread_unread || 0 }) }
  if (!a.enabled) return { id: 'off', tone: 'idle', text: t('agents.side.state.off') }
  if (last?.kind === 'result' && last.ok === false) return { id: 'failed', tone: 'error', text: t('agents.lastFailed', { when: fmtRelative(last.at, lang) }) }
  if (!last) return { id: 'idle', tone: 'idle', text: t('agents.neverRun') }
  return { id: 'idle', tone: 'ok', text: t('agents.overview.ran', { when: fmtRelative(last.at, lang) }) }
}

/** An agent: its character behind its desk, its name, its status; Run and the switch on hover. */
function AgentTile({ agent: a }: { agent: Agent }) {
  const t = useT()
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
      className="group/tile relative grid cursor-pointer justify-items-center gap-3 rounded-xl border bg-card px-3 pt-5 pb-4 text-center transition-colors hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      data-testid="agent-card"
      data-state={s.id}
    >
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

/** No agent yet: one character waiting at its desk, what an agent is, and the way to create the first one. */
function EmptyOverview({ onNew }: { onNew: () => void }) {
  const t = useT()
  return (
    <div className="grid justify-items-center gap-5 py-12 text-center" data-testid="agents-empty">
      <AtDesk />
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
