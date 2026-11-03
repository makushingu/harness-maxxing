// One agent (/agents/<project>/<topic>/<name>): its face, Run (with an optional text) and "Open a session" in the
// header; tabs Activity (its thread: a message per run, newest at the bottom, live on the bus topic "agents") /
// Role (CLAUDE.md) / Memory (memory.md) / Triggers / Settings. The tab is in the URL (?tab=).
import * as React from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { AlertTriangle, ArrowLeft, Bot, CheckCircle2, ExternalLink, MessageSquarePlus, Pencil, Play, StickyNote, XCircle } from 'lucide-react'
import { useLang, useT, type TFn } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useAgent, useAgentThread, useCrons, useFileContent, usePatchAgent, useWorkspace, useWriteFile } from '@/lib/queries'
import type { AgentDetail, AgentMessage, Cron } from '@/lib/types'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  Badge, Button, EmptyState, Popover, PopoverContent, PopoverTrigger, Sensitive, Skeleton, StatusDot, Switch, Tabs, TabsContent, TabsList, TabsTrigger,
  Textarea, Tooltip, toast,
} from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { absTopicDir, filesUrl, fmtCost, linkifyMarkdown, sessionsUrl } from '@/pages/sessions/util'
import { AgentAvatarIcon } from './Avatar'
import { AgentTriggers } from './AgentTriggers'
import { AgentSettings } from './AgentSettings'
import { AgentsOff, TriggerChips, costLine, reasonText, useAgentsOn, useRunNow } from './parts'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

type Tab = 'activity' | 'role' | 'memory' | 'triggers' | 'settings'
const TABS: Tab[] = ['activity', 'role', 'memory', 'triggers', 'settings']

export default function AgentPage() {
  const t = useT()
  const on = useAgentsOn()
  const { project = '', topic = '', name = '' } = useParams()
  const path = `projects/${project}/topics/${topic}/agents/${name}`
  const { data: a, isLoading, error, refetch } = useAgent(on === false ? null : path)
  const [params, setParams] = useSearchParams()
  const tab = (TABS as string[]).includes(params.get('tab') || '') ? (params.get('tab') as Tab) : 'activity'
  const setTab = (v: string) =>
    setParams(
      (p) => {
        if (v === 'activity') p.delete('tab')
        else p.set('tab', v)
        return p
      },
      { replace: true },
    )
  const back = (
    <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.back')} className="-ml-1">
      <Link to="/agents">
        <ArrowLeft />
      </Link>
    </Button>
  )

  if (on === false) return <AgentsOff />
  if (isLoading || on === undefined)
    return (
      <Page title={name} leading={back} width="wide">
        <Skeleton className="h-36 rounded-xl" />
        <Skeleton className="mt-4 h-80 rounded-xl" />
      </Page>
    )
  if (error || !a)
    return (
      <Page title={name} leading={back}>
        <EmptyState
          icon={Bot}
          tone="error"
          title={t('agents.notFound')}
          description={errorMessage(error)}
          action={
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                {t('common.retry')}
              </Button>
              <Button asChild size="sm">
                <Link to="/agents">{t('agents.backToList')}</Link>
              </Button>
            </div>
          }
        />
      </Page>
    )

  return (
    <Page
      title={<Sensitive length={8}>{a.display_name}</Sensitive>}
      description={<Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>}
      leading={back}
      width="wide"
      actions={<HeaderActions agent={a} />}
    >
      <Hero agent={a} />
      <Tabs value={tab} onValueChange={setTab} className="mt-5">
        <div className="-mx-1 overflow-x-auto px-1">
          <TabsList>
            {TABS.map((x) => (
              <TabsTrigger key={x} value={x} data-testid={`agent-tab-${x}`}>
                {t(`agents.tab.${x}` as 'agents.tab.activity')}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="activity" className="mt-4">
          <Activity agent={a} />
        </TabsContent>
        <TabsContent value="role" className="mt-4">
          <RoleTab agent={a} />
        </TabsContent>
        <TabsContent value="memory" className="mt-4">
          <MemoryTab agent={a} />
        </TabsContent>
        <TabsContent value="triggers" className="mt-4">
          <AgentTriggers agent={a} />
        </TabsContent>
        <TabsContent value="settings" className="mt-4">
          <AgentSettings agent={a} />
        </TabsContent>
      </Tabs>
    </Page>
  )
}

/** Run (optional text) and "Open a session" (the new-session composer in the agent's folder). */
function HeaderActions({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const navigate = useNavigate()
  const run = useRunNow()
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState('')
  const go = () => run.go(a, text.trim() || undefined, () => (setOpen(false), setText('')))
  return (
    <>
      <Tooltip content={t('agents.openSessionTip')}>
        <Button variant="outline" size="sm" onClick={() => navigate(`/sessions?path=${encodeURIComponent(a.path)}&new=1`)} data-testid="agent-open-session">
          <MessageSquarePlus /> <span className="max-sm:sr-only">{t('agents.openSession')}</span>
        </Button>
      </Tooltip>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button size="sm" disabled={!a.enabled} data-testid="agent-run-open">
            <Play /> <span className="max-sm:sr-only">{t('agents.run.button')}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="grid w-80 gap-3">
          <div className="grid gap-1">
            <span className="text-sm font-medium">{t('agents.run.title', { name: a.display_name })}</span>
            <span className="text-xs text-muted-foreground">{t('agents.run.textHint')}</span>
          </div>
          <Textarea
            autoFocus
            minRows={3}
            maxRows={10}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t('agents.run.placeholder')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                go()
              }
            }}
            data-testid="agent-run-text"
          />
          <div className="flex justify-end">
            <Button size="sm" loading={run.pending} onClick={go} data-testid="agent-run">
              <Play /> {t('agents.run.now')}
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </>
  )
}

function Hero({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  const running = (a.running_now || a.running || 0) > 0
  return (
    <div className="flex flex-wrap items-start gap-4 rounded-xl border bg-card p-4 sm:flex-nowrap sm:p-5">
      <AgentAvatarIcon avatar={a.avatar} size={96} className="max-sm:size-16" />
      <div className="grid min-w-0 flex-1 gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-lg font-semibold">
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          {running ? <Badge variant="default" className="gap-1"><StatusDot tone="running" pulse className="size-1.5" /> {t('agents.runningNow')}</Badge> : !a.enabled && <Badge variant="muted">{t('agents.paused')}</Badge>}
          <Link to={`/sessions?path=${encodeURIComponent(`projects/${a.project}/topics/${a.topic}`)}`} className="text-xs text-muted-foreground hover:text-foreground hover:underline">
            <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
          </Link>
        </div>
        <p className="line-clamp-3 text-sm whitespace-pre-line text-muted-foreground">{a.description ? <Sensitive block>{a.description}</Sensitive> : <span className="italic">{t('agents.noRole')}</span>}</p>
        <TriggerChips agent={a} crons={a.crons} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="tabular-nums">
            <Sensitive length={6}>{costLine(t, a)}</Sensitive>
          </span>
          {a.limits.runs_per_hour > 0 && <span className="tabular-nums">{t('agents.runsHour', { count: a.runs_last_hour || 0, max: a.limits.runs_per_hour })}</span>}
          <span className="tabular-nums">{t('agents.sessionsCount', { count: a.session_count + a.archived_count })}</span>
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm max-sm:w-full">
        <Switch checked={a.enabled} onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })} data-testid="agent-enabled" />
        {a.enabled ? t('agents.on') : t('agents.offShort')}
      </label>
    </div>
  )
}

/* ---------------------------------------------------------------- Activity (the thread) */
export function triggerLabel(t: TFn, m: Pick<AgentMessage, 'trigger' | 'source'>, crons: Cron[] = []): string {
  const tr = m.trigger || ''
  if (tr === 'manual' || m.source === 'manual') return t('agents.from.manual')
  if (tr.startsWith('cron:')) {
    const j = crons.find((c) => c.id === tr.slice(5))
    return j ? t('agents.from.cronNamed', { name: j.name }) : t('agents.from.cron')
  }
  if (tr === 'telegram' || m.source === 'telegram') return t('agents.from.telegram')
  if (tr.startsWith('agent:')) return t('agents.from.agent', { name: tr.slice(6).split('/').pop() || '' })
  if (tr.startsWith('feed:')) return m.source ? t('agents.from.feedNamed', { source: m.source }) : t('agents.from.feed')
  return m.source || tr || t('agents.from.manual')
}

function Activity({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data, isLoading, error } = useAgentThread(a.path)
  const { data: crons } = useCrons()
  const { data: ws } = useWorkspace()
  const box = React.useRef<HTMLDivElement>(null)
  const msgs = data?.messages || []
  const last = msgs[msgs.length - 1]?.id
  // Newest at the bottom: follow it when a message arrives (unless the user scrolled up to read).
  const stick = React.useRef(true)
  React.useLayoutEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [last])
  if (isLoading)
    return (
      <div className="grid gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className={cn('h-16 rounded-xl', i % 2 && 'ml-10')} />
        ))}
      </div>
    )
  if (error) return <EmptyState tone="error" compact title={t('agents.thread.error')} description={errorMessage(error)} />
  if (!msgs.length) return <EmptyState icon={StickyNote} compact title={t('agents.thread.empty')} description={t('agents.thread.emptyDesc')} />
  return (
    <div
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
      className="grid max-h-[calc(100dvh-22rem)] min-h-64 content-start gap-3 overflow-y-auto rounded-xl border bg-muted/20 p-3 sm:p-4 max-md:max-h-none"
      data-testid="agent-thread"
      aria-live="polite"
    >
      {msgs.map((m) => (
        <ThreadMessage key={m.id} m={m} agent={a} crons={crons?.jobs || []} root={ws?.root} />
      ))}
    </div>
  )
}

function ThreadMessage({ m, agent: a, crons, root }: { m: AgentMessage; agent: AgentDetail; crons: Cron[]; root?: string }) {
  const t = useT()
  const lang = useLang()
  const when = <time className="text-[11px] text-muted-foreground tabular-nums" dateTime={new Date(m.at * 1000).toISOString()} title={fmtDate(m.at, lang)}>{fmtRelative(m.at, lang)}</time>
  const sessionLink = m.session && (
    <Link to={sessionsUrl({ id: m.session, path: a.path })} className="inline-flex items-center gap-1 text-xs text-primary hover:underline pointer-coarse:min-h-10">
      <ExternalLink className="size-3" /> {t('agents.thread.openSession')}
    </Link>
  )
  if (m.kind === 'note')
    return (
      <div className="flex items-center justify-center gap-2 py-1 text-xs text-muted-foreground" data-kind="note">
        <span className="h-px w-6 bg-border" aria-hidden />
        <Sensitive>{m.text}</Sensitive> · {when}
        <span className="h-px w-6 bg-border" aria-hidden />
      </div>
    )
  if (m.kind === 'skip')
    return (
      <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm" data-kind="skip">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span>
            {t('agents.thread.skipped', { from: triggerLabel(t, m, crons) })} <span className="text-muted-foreground">{reasonText(t, m.reason) || m.text}</span>
          </span>
          {when}
        </div>
      </div>
    )
  if (m.kind === 'run')
    return (
      <div className="ml-auto grid w-fit max-w-[85%] gap-1 rounded-xl rounded-br-sm bg-primary/10 px-3 py-2 text-sm max-sm:max-w-full" data-kind="run">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <Play className="size-3 text-primary" />
          <span className="font-medium text-foreground">{t('agents.thread.started', { from: triggerLabel(t, m, crons) })}</span>
          {when}
        </div>
        {m.text && (
          <p className="line-clamp-6 whitespace-pre-wrap break-words">
            <Sensitive block>{m.text}</Sensitive>
          </p>
        )}
        {sessionLink}
      </div>
    )
  // result / approval: the agent speaks
  const failed = m.kind === 'result' && m.ok === false
  return (
    <div className="flex items-start gap-2" data-kind={m.kind}>
      <AgentAvatarIcon avatar={a.avatar} size={28} className="mt-0.5" />
      <div className={cn('grid min-w-0 max-w-[85%] gap-1.5 rounded-xl rounded-tl-sm border bg-card px-3 py-2 max-sm:max-w-full', failed && 'border-destructive/40', m.kind === 'approval' && 'border-warning/40 bg-warning/5')}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
          <span className="font-medium">
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          {m.kind === 'approval' ? (
            <Badge variant="warning">{t('agents.thread.approval')}</Badge>
          ) : failed ? (
            <span className="inline-flex items-center gap-1 text-destructive">
              <XCircle className="size-3" /> {t('agents.thread.failed')}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-success">
              <CheckCircle2 className="size-3" /> {t('agents.thread.done')}
            </span>
          )}
          {when}
          {m.cost != null && m.cost > 0 && <span className="text-muted-foreground tabular-nums">· {fmtCost(m.cost)}</span>}
        </div>
        {m.text ? (
          <div className="min-w-0 text-sm">
            <Sensitive block>
              <React.Suspense fallback={<p className="whitespace-pre-wrap break-words">{m.text}</p>}>
                <Markdown className="text-sm">{linkifyMarkdown(m.text, root)}</Markdown>
              </React.Suspense>
            </Sensitive>
          </div>
        ) : (
          <span className="text-sm text-muted-foreground italic">{t('agents.thread.noText')}</span>
        )}
        {sessionLink}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- Role */
function RoleTab({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  const { data: ws } = useWorkspace()
  const [v, setV] = React.useState(a.description)
  const [dirty, setDirty] = React.useState(false)
  React.useEffect(() => {
    if (!dirty) setV(a.description)
  }, [a.description, dirty])
  const dir = absTopicDir(ws, a.path)
  return (
    <div className="grid max-w-3xl gap-3">
      <p className="text-sm text-muted-foreground">{t('agents.role.desc')}</p>
      <Textarea
        minRows={8}
        maxRows={30}
        value={v}
        onChange={(e) => {
          setV(e.target.value)
          setDirty(true)
        }}
        placeholder={t('agents.create.rolePlaceholder')}
        data-testid="agent-role-edit"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={!dirty}
          loading={patch.isPending}
          onClick={() => patch.mutate({ path: a.path, description: v }, { onSuccess: () => (setDirty(false), toast.success(t('agents.role.saved'))) })}
          data-testid="agent-role-save"
        >
          {t('common.save')}
        </Button>
        {dirty && (
          <Button variant="ghost" onClick={() => (setV(a.description), setDirty(false))}>
            {t('common.cancel')}
          </Button>
        )}
        {dir && (
          <Button asChild variant="link" className="ml-auto">
            <Link to={filesUrl(`${dir}/CLAUDE.md`)}>
              <ExternalLink /> {t('agents.role.openFile')}
            </Link>
          </Button>
        )}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- Memory */
function MemoryTab({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data: ws } = useWorkspace()
  const dir = absTopicDir(ws, a.path)
  const file = dir ? `${dir}/memory.md` : null
  const { data, isLoading, error, refetch } = useFileContent(file)
  const write = useWriteFile()
  const [edit, setEdit] = React.useState<string | null>(null)
  if (isLoading || !file) return <Skeleton className="h-60 rounded-xl" />
  if (error)
    return (
      <EmptyState
        compact
        icon={StickyNote}
        title={t('agents.memory.none')}
        description={t('agents.memory.noneDesc')}
        action={
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            {t('common.retry')}
          </Button>
        }
      />
    )
  const content = data?.content || ''
  return (
    <div className="grid max-w-3xl gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">{t('agents.memory.desc')}</p>
        {edit === null && data?.editable !== false && (
          <Button size="sm" variant="outline" onClick={() => setEdit(content)} data-testid="agent-memory-edit">
            <Pencil /> {t('common.edit')}
          </Button>
        )}
        <Button asChild size="sm" variant="ghost">
          <Link to={filesUrl(file)}>
            <ExternalLink /> {t('agents.memory.openFile')}
          </Link>
        </Button>
      </div>
      {edit !== null ? (
        <>
          <Textarea minRows={10} maxRows={40} value={edit} onChange={(e) => setEdit(e.target.value)} className="font-mono text-[13px]" />
          {write.error && <p className="text-sm text-destructive">{errorMessage(write.error)}</p>}
          <div className="flex gap-2">
            <Button
              loading={write.isPending}
              onClick={() =>
                write.mutate({ path: file, content: edit, expected_mtime: data?.mtime }, { onSuccess: () => (setEdit(null), toast.success(t('agents.memory.saved')), refetch()) })
              }
            >
              {t('common.save')}
            </Button>
            <Button variant="ghost" onClick={() => setEdit(null)}>
              {t('common.cancel')}
            </Button>
          </div>
        </>
      ) : content.trim() ? (
        <div className="rounded-xl border bg-card p-4">
          <Sensitive block>
            <React.Suspense fallback={<pre className="text-sm whitespace-pre-wrap">{content}</pre>}>
              <Markdown className="text-sm">{content}</Markdown>
            </React.Suspense>
          </Sensitive>
        </div>
      ) : (
        <EmptyState compact icon={StickyNote} title={t('agents.memory.empty')} description={t('agents.memory.emptyDesc')} />
      )}
    </div>
  )
}
