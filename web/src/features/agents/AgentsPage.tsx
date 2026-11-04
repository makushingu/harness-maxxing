// The overview of the Agents page (/agents with no agent selected, the right pane of AgentsLayout): one card per
// agent, "To read" first, then grouped by project; the agent's own page is /agents/<project>/<topic>/<name>.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Bot, Play, Plus, ShieldCheck } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentRoute, useAgents, useCrons, usePatchAgent, useWorkspace } from '@/lib/queries'
import type { Agent, Cron } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge, Button, EmptyState, Select, Sensitive, Skeleton, StatusDot, Switch, Tooltip, useMask } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { AgentAvatarIcon } from './Avatar'
import { TriggerChips, costLine, firstLine, reasonText, useAgentsOn, useRunNow } from './parts'

export function AgentsOverview({ onNew }: { onNew: () => void }) {
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
  // "To read" first (a new result, waiting for an OK, working now), then the others by project.
  const hot = (a: Agent) => (a.thread_unread || 0) > 0 || (a.waiting || 0) > 0 || (a.running_now || 0) > 0
  const shown = React.useMemo(() => agents.filter((a) => project === '_all' || a.project === project), [agents, project])
  const toRead = React.useMemo(() => shown.filter(hot), [shown])
  const groups = React.useMemo(() => {
    const g = new Map<string, Agent[]>()
    for (const a of shown) if (!hot(a)) g.set(a.project, [...(g.get(a.project) || []), a])
    return [...g.entries()]
  }, [shown])
  const emoji = (p: string) => ws?.projects.find((x) => x.name === p)?.emoji || ''

  return (
    <Page
      title={t('agents.side.overview')}
      description={t('agents.desc')}
      actions={
        <>
          {projects.length > 1 && (
            <Select
              value={project}
              onValueChange={setProject}
              aria-label={t('agents.filterProject')}
              className="w-40 max-sm:w-32"
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
        <EmptyState
          icon={Bot}
          title={t('agents.emptyTitle')}
          description={
            <span className="mx-auto grid max-w-lg gap-2">
              <span>{t('agents.emptyDesc')}</span>
              <span>{t('agents.emptyDesc2')}</span>
            </span>
          }
          action={
            <Button onClick={onNew}>
              <Plus /> {t('agents.create')}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-8">
          {toRead.length > 0 && (
            <section className="grid gap-3" aria-label={t('agents.list.toRead')} data-testid="agents-to-read">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                {t('agents.list.toRead')} <Badge variant="default" className="h-4 px-1.5 text-[10px]">{toRead.length}</Badge>
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {toRead.map((a) => (
                  <AgentCard key={a.path} agent={a} crons={cronsOf.get(a.path) || []} />
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
                  <AgentCard key={a.path} agent={a} crons={cronsOf.get(a.path) || []} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Page>
  )
}

function AgentCard({ agent: a, crons }: { agent: Agent; crons: Cron[] }) {
  const t = useT()
  const lang = useLang()
  const navigate = useNavigate()
  const patch = usePatchAgent()
  const run = useRunNow()
  const open = () => navigate(agentRoute(a))
  const last = a.last_run
  const running = (a.running_now || a.running || 0) > 0
  return (
    <li>
      <div
        role="link"
        tabIndex={0}
        onClick={open}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open())}
        className={cn('flex h-full cursor-pointer flex-col gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', !a.enabled && 'opacity-75')}
        data-testid="agent-card"
      >
        <div className="flex items-start gap-3">
          <AgentAvatarIcon avatar={a.avatar} size={44} />
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
    </li>
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
