// The overview of the Agents page, the Office (/agents with no agent selected, the right pane of AgentsLayout on a
// computer; /agents/office on a phone). Its views, picked in the menu at the top right (ViewMenu) and kept per
// browser: Classic (below), Space (a pixel-art office on a space station,
// OfficeFuture.tsx), then the views extensions bring (OfficeCustom.tsx) and "Create my custom view" (a new session of
// general/inbox that builds one with the skill maxxing-extension). Classic:
// one section per project (dot in the project colour, name, count, "..." menu, like the lanes of Tasks; order, colours
// and drag and drop of projects and agents: layout.tsx), each agent a card with
// its character sitting behind a small desk, its name and one status line in words. A small bubble above the head
// only when something matters (working, new results, waiting for an OK, failed). The whole card opens the agent;
// Run and the on/off switch show on hover or focus (always on touch screens).
// The agent's own page is /agents/<project>/<topic>/<name>; on a phone /agents is the list (AgentsList).
import * as React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ChevronDown, LayoutGrid, Play, Plus, Rocket, UsersRound, WandSparkles } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { agentRoute, newGroupRoute, useAgents, useExtensions, usePatchAgent, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { errorMessage } from '@/lib/api'
import { cn, store } from '@/lib/utils'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  NamedIcon,
  Sheet,
  SheetContent,
  SheetTitle,
  Sensitive,
  Skeleton,
  StatusDot,
  Switch,
  Tooltip,
  useMask,
} from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { AgentAvatarIcon, DEFAULT_AVATAR, OUTFIT } from './Avatar'
import { statusOf, useAgentsOn, useRunNow, type Status } from './parts'
import { WaitingBubble } from './approvals'
import { QuickCreate, type CreateStart } from './CreateAgent'
import { OfficeFuture } from './OfficeFuture'
import { OfficeCustom } from './OfficeCustom'
import { OfficeChat } from './office'
import { AgentChatPanel } from './AgentPage'
import { useMediaQuery } from '@/stores/media'
import { draftUrl } from './EditWithClaude'
import { DropBar, ProjectMenu, useAgentsLayout, useReorder, type AgentsLayoutApi } from './layout'
import { SilentMark, useAgentMenu } from './AgentMenu'

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3'

/** A built-in view, or `x:<extension id>` (a view an extension brings). */
export type OfficeView = 'classic' | 'future' | `x:${string}`
const VIEW_KEY = 'mx-agents-office-view'
const BUILTIN_VIEWS = [
  { id: 'classic', icon: LayoutGrid, label: 'agents.office.classic' },
  { id: 'future', icon: Rocket, label: 'agents.office.future' },
] as const

/** The view of the Office, kept per browser (Classic by default). */
function useOfficeView(): [OfficeView, (v: OfficeView) => void] {
  const [v, setV] = React.useState<OfficeView>(() => {
    const x = store.get(VIEW_KEY) || ''
    // `game` = the former Gamified view, replaced by Space.
    if (x === 'game') return 'future'
    return x === 'future' || /^x:[a-z0-9][a-z0-9-]{0,47}$/.test(x) ? (x as OfficeView) : 'classic'
  })
  const set = React.useCallback((x: OfficeView) => {
    store.set(VIEW_KEY, x)
    setV(x)
  }, [])
  return [v, set]
}

/** The Office views extensions bring (manifest "agents_view"), the ones that work now. */
function useCustomViews() {
  const { data, isLoading } = useExtensions()
  const views = React.useMemo(
    () => (data || []).filter((e) => e.enabled && !e.error && e.agents_view).map((e) => ({ id: e.id, name: e.agents_view!.name, icon: e.agents_view!.icon })),
    [data],
  )
  return { views, loading: isLoading }
}

/** Where "Create my custom view" opens its session: general/inbox when it exists, else the first topic out of system. */
function useCustomViewTopic(): string {
  const { data: ws } = useWorkspace()
  const topics = (ws?.projects || []).flatMap((p) => p.topics.map((tp) => ({ project: p.name, path: tp.path })))
  return (topics.find((x) => x.path === 'projects/general/topics/inbox') || topics.find((x) => x.project !== 'system') || topics[0])?.path || 'projects/general/topics/inbox'
}

/** New group (outline) + New agent (primary): the top right of the Office, and of the list on a phone. A list narrowed to
 *  a topic (?topic=) starts the group in its project. */
export function NewButtons({ onNew }: { onNew: () => void }) {
  const t = useT()
  const [params] = useSearchParams()
  const project = (params.get('topic') || '').split('/')[0] || undefined
  return (
    <>
      <Button asChild size="sm" variant="outline" data-testid="group-new" data-tour="group-new">
        <Link to={newGroupRoute(project)}>
          <UsersRound /> <span className="max-[429px]:sr-only">{t('groups.new')}</span>
        </Link>
      </Button>
      <Button size="sm" onClick={onNew} data-testid="agent-new">
        <Plus /> <span className="max-[429px]:sr-only">{t('agents.new')}</span>
      </Button>
    </>
  )
}

export function AgentsOverview({ onNew, onStart }: { onNew: () => void; onStart: (s: CreateStart) => void }) {
  const t = useT()
  const on = useAgentsOn()
  const { data, isLoading, error, refetch } = useAgents(on !== false)
  const agents = React.useMemo(() => data?.agents || [], [data])
  const [picked, setView] = useOfficeView()
  const custom = useCustomViews()
  // A view of an extension that is gone (deleted, off, in error) shows Classic; the choice is kept for when it is back.
  const ext = picked.startsWith('x:') ? custom.views.find((v) => `x:${v.id}` === picked) : undefined
  const view: OfficeView = picked.startsWith('x:') && !ext && !custom.loading ? 'classic' : picked
  // Projects and agents in the order of the layout (picked by hand, else workspace order / topic then name).
  const layout = useAgentsLayout()
  const groups = React.useMemo(() => layout.group(agents), [agents, layout])
  // ?chat=<agent path>: its conversation next to the Office (a sheet on a narrow screen); a desk opens it, the same
  // desk again closes it. Back (the browser's) closes it too.
  const [search, setSearch] = useSearchParams()
  const chat = search.get('chat')
  const setChat = React.useCallback(
    (path: string | null) =>
      setSearch((p) => {
        const n = new URLSearchParams(p)
        if (path) n.set('chat', path)
        else n.delete('chat')
        return n
      }),
    [setSearch],
  )
  const office = React.useMemo(() => ({ open: (path: string) => setChat(path === chat ? null : path), current: chat }), [chat, setChat])
  const docked = useMediaQuery('(min-width: 1024px)')

  const page = (
    <Page
      title={t('agents.side.office')}
      description={t('agents.desc')}
      width={view === 'classic' ? 'default' : 'wide'}
      actions={
        <>
          {agents.length > 0 && <ViewMenu view={view} custom={custom.views} onChange={setView} />}
          <NewButtons onNew={onNew} />
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
      ) : view === 'future' ? (
        <OfficeFuture groups={groups} layout={layout} onStart={onStart} />
      ) : view.startsWith('x:') ? (
        ext ? <OfficeCustom ext={ext} groups={groups} layout={layout} /> : <Skeleton className="h-[40rem] rounded-xl" />
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
  return (
    <OfficeChat.Provider value={office}>
      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">{page}</div>
        {chat && docked && (
          <aside className="flex w-[440px] shrink-0 flex-col border-l bg-background" data-testid="office-chat-panel">
            <AgentChatPanel key={chat} path={chat} onClose={() => setChat(null)} />
          </aside>
        )}
      </div>
      {!docked && (
        <Sheet open={!!chat} onOpenChange={(o) => !o && setChat(null)}>
          <SheetContent side="right" hideClose className="h-[calc(var(--vvh,100dvh)*0.92)]" data-testid="office-chat-panel">
            <SheetTitle className="sr-only">{t('agents.office.chat')}</SheetTitle>
            {chat && <AgentChatPanel key={chat} path={chat} onClose={() => setChat(null)} />}
          </SheetContent>
        </Sheet>
      )}
    </OfficeChat.Provider>
  )
}

/** The view picker: the current view's icon and name; the built-in views, the ones of extensions, then "Create my
 *  custom view" (a new session that builds one as an extension, its request already typed). */
function ViewMenu({ view, custom, onChange }: { view: OfficeView; custom: { id: string; name: string; icon: string }[]; onChange: (v: OfficeView) => void }) {
  const t = useT()
  const navigate = useNavigate()
  const topic = useCustomViewTopic()
  const builtin = BUILTIN_VIEWS.find((v) => v.id === view)
  const ext = custom.find((v) => `x:${v.id}` === view)
  const icon = builtin ? <builtin.icon /> : <NamedIcon name={ext?.icon} />
  const name = builtin ? t(builtin.label) : ext?.name || t('agents.office.classic')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`${t('agents.office.view')}: ${name}`} data-testid="agents-office-view" data-view={view}>
          {icon}
          <span className="max-w-40 truncate max-sm:sr-only">{name}</span>
          <ChevronDown className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel>{t('agents.office.view')}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={view} onValueChange={(v) => onChange(v as OfficeView)}>
          {BUILTIN_VIEWS.map((v) => (
            <DropdownMenuRadioItem key={v.id} value={v.id} data-testid={`agents-view-${v.id}`}>
              <v.icon /> {t(v.label)}
            </DropdownMenuRadioItem>
          ))}
          {custom.map((v) => (
            <DropdownMenuRadioItem key={v.id} value={`x:${v.id}`} data-testid={`agents-view-x-${v.id}`}>
              <NamedIcon name={v.icon} /> <span className="truncate">{v.name}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate(draftUrl(topic, t('agents.office.customPrompt')))} data-testid="agents-view-create">
          <WandSparkles /> {t('agents.office.custom')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** A project of the Classic view: its header (colour, name, count, "..."), dragged to move the whole section. */
function ProjectSection({ project: p, count: n, index, layout, children }: { project: string; count: number; index: number; layout: AgentsLayoutApi; children: React.ReactNode }) {
  const t = useT()
  const mask = useMask()
  const dnd = useReorder({ kind: 'project', id: p, project: p, index }, (x) => layout.moveProject(x, p))
  return (
    <section {...dnd.target} className={cn('relative grid grid-cols-[minmax(0,1fr)] gap-3 rounded-xl', dnd.dragging && 'opacity-50')} aria-label={p} data-testid="agents-project" data-project={p}>
      <DropBar side={dnd.side} className="inset-x-0 h-1" />
      <h2 {...dnd.source} className={cn('group/head flex min-w-0 items-center gap-2 px-0.5 text-[13px] font-semibold', dnd.on && 'cursor-grab active:cursor-grabbing')} title={dnd.on ? t('agents.layout.dragProject') : undefined} data-testid="agents-project-head">
        <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: OUTFIT[layout.colorOf(p)] }} data-testid="agents-project-dot" />
        <span className="min-w-0 truncate" title={mask(p, 8)}>
          <Sensitive length={8}>{p}</Sensitive>
        </span>
        <span className="shrink-0 text-xs font-normal text-muted-foreground tabular-nums">{t('agents.overview.count', { count: n })}</span>
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
  const chat = React.useContext(OfficeChat)
  const open = () => (chat ? chat.open(a.path) : navigate(agentRoute(a)))
  const current = chat?.current === a.path
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  const ctx = useAgentMenu(a)
  return (
    <div
      role="link"
      tabIndex={0}
      aria-label={t('agents.overview.open', { name: a.display_name })}
      onClick={open}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), open())}
      {...dnd.props}
      {...ctx.props}
      className={cn(
        'group/tile relative grid cursor-pointer justify-items-center gap-3 rounded-xl border bg-card px-3 pt-5 pb-4 text-center transition-colors hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        dnd.dragging && 'opacity-50',
        dnd.side && 'border-primary',
        current && 'border-primary bg-accent/30',
      )}
      aria-current={current || undefined}
      data-testid="agent-card"
      data-state={s.id}
      data-path={a.path}
    >
      <DropBar side={dnd.side} vertical={false} />
      <AtDesk agent={a} status={s} />
      <div className="grid w-full min-w-0 gap-0.5">
        <span className="flex min-w-0 items-center justify-center gap-1">
          <span className={cn('truncate text-sm font-medium', !a.enabled && 'text-muted-foreground')}>
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          <SilentMark agent={a} />
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
      {ctx.menu}
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
      // A quest marker: a big yellow "!" with a dark outline that hops, no bubble around it.
      <WaitingBubble agent={a} className="absolute -top-4 -right-2 z-20 grid h-8 w-6 place-items-center rounded-sm transition-transform hover:scale-115">
        <span className="mx-game-hop text-[26px] leading-none font-black text-[#ffcc4d] [paint-order:stroke_fill] [-webkit-text-stroke:3px_#3b2a00] drop-shadow-[0_1px_0_rgb(0_0_0/0.35)]">
          !
        </span>
      </WaitingBubble>
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
