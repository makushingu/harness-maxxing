// One agent group (/agents/groups/<project>/<name>) as a group chat: the owner writes, 2-6 agents of the project answer
// in turn (server: agent_rooms.py).
// - the header: its emoji and name, Stop while someone speaks or waits to, "…" = Edit, New topic, Open the shared
//   folder, Delete; under it the members (face, name, role; "writing…" for the one speaking, dimmed when paused, with
//   Let speak again; a member's menu opens its agent page, pauses it, or names it in the box);
// - the conversation: my messages on the right, the members' answers on the left (markdown, long ones folded, "See
//   the run" opens the turn's session in place), "X passes", "X could not speak" and the system lines (created, New
//   topic, limit reached, Stopped) centered; a member waiting for an approval shows the request at the bottom;
// - the box: Enter sends, `@` lists the members (and @all) to pick who answers.
// Opening the group marks it read (POST /seen), again when an answer comes in while it is open.
import * as React from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import {
  ArrowLeft, AtSign, Bot, FolderOpen, MoreHorizontal, Pause, Pencil, Play, PlayCircle, RotateCcw, Send, ShieldCheck, Square, Trash2, UsersRound, WandSparkles,
} from 'lucide-react'
import { useLang, useT, type TFn } from '@/i18n'
import { errorMessage } from '@/lib/api'
import {
  agentRoute, agentRunRoute, useAgentGroup, useAgents, useDeleteGroup, useGroupMessages, useGroupPause, useGroupReset, useGroupSay, useGroupSeen, useGroupStop,
  usePendingApprovals, useWorkspace,
} from '@/lib/queries'
import type { AgentGroup, AgentGroupMember, AgentGroupMessage, Approval } from '@/lib/types'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCompact } from '@/stores/media'
import {
  Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger, EmptyState, Sensitive, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle, Skeleton, StatusDot, Textarea,
  Tooltip, confirm,
} from '@/components/ui'
import { Page, PageHeader } from '@/components/shell/Page'
import { ApprovalCard } from '@/pages/sessions/Approvals'
import { absTopicDir, filesUrl, fmtCost, linkifyMarkdown } from '@/pages/sessions/util'
import { AgentAvatarIcon } from './Avatar'
import { GroupFace } from './AgentsList'
import { GroupForm, claudeTopic } from './GroupForm'
import { draftUrl } from './EditWithClaude'
import { AgentsOff, reasonText, useAgentsOn } from './parts'
import { MentionChip, mentionComponents, mentionNodes, namedIn, useMentionMap, type MentionMap } from './mentions'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))

/** An answer longer than this is folded (the first lines and "Read all"), as on an agent's page. */
const FOLD_CHARS = 700

const slugOf = (path: string) => path.split('/').pop() || ''

export default function GroupPage() {
  const t = useT()
  const on = useAgentsOn()
  const touch = useCompact()
  const { project = '', name = '' } = useParams()
  const path = `projects/${project}/groups/${name}`
  const { data: g, isLoading, error, refetch } = useAgentGroup(on === false ? null : path)
  const [editing, setEditing] = React.useState(false)
  const composer = React.useRef<ComposerApi>(null)
  const back = touch ? (
    <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.back')} className="-ml-1">
      <Link to="/agents">
        <ArrowLeft />
      </Link>
    </Button>
  ) : null

  if (on === false) return <AgentsOff />
  if (isLoading || on === undefined)
    return (
      <Page title={name} leading={back} width="wide">
        <Skeleton className="h-10 rounded-xl" />
        <Skeleton className="mt-4 h-80 rounded-xl" />
      </Page>
    )
  if (error || !g)
    return (
      <Page title={name} leading={back}>
        <EmptyState
          icon={UsersRound}
          tone="error"
          title={t('groups.notFound')}
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
    <div className="flex h-full min-h-0 flex-col" data-testid="group-page">
      <PageHeader
        leading={
          <div className="flex items-center gap-2">
            {back}
            <GroupFace group={g} size={32} />
          </div>
        }
        title={
          <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 truncate">
              <Sensitive length={8}>{g.display_name}</Sensitive>
            </span>
            {g.busy && (
              <Badge variant="default" className="shrink-0 gap-1 max-sm:hidden">
                <StatusDot tone="running" pulse className="size-1.5" /> {t('groups.busy')}
              </Badge>
            )}
          </span>
        }
        description={
          <span className="truncate">
            <Sensitive length={8}>{g.project}</Sensitive> · {t('groups.members', { count: g.members.length })}
          </span>
        }
        actions={
          <>
            {g.busy && <StopButton group={g} />}
            <GroupMenu group={g} onEdit={() => setEditing(true)} />
          </>
        }
      />
      <MemberBar group={g} onMention={(slug) => composer.current?.mention(slug)} />
      <Conversation group={g} composer={composer} />
      <Sheet open={editing} onOpenChange={setEditing}>
        <SheetContent className="md:w-[560px]" data-testid="group-edit">
          <SheetHeader>
            <SheetTitle>{t('groups.edit.title')}</SheetTitle>
            <SheetDescription>{t('groups.edit.desc')}</SheetDescription>
          </SheetHeader>
          <SheetBody className="grid content-start gap-5">{editing && <GroupForm group={g} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} />}</SheetBody>
        </SheetContent>
      </Sheet>
    </div>
  )
}

function StopButton({ group: g }: { group: AgentGroup }) {
  const t = useT()
  const stop = useGroupStop()
  return (
    <Button variant="outline" size="sm" onClick={() => stop.mutate({ path: g.path })} loading={stop.isPending} data-testid="group-stop">
      <Square /> <span className="max-sm:sr-only">{t('groups.stop')}</span>
    </Button>
  )
}

/** "…": Edit, New topic, the shared folder, Delete (with the choice to keep the shared files). */
function GroupMenu({ group: g, onEdit }: { group: AgentGroup; onEdit: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const reset = useGroupReset()
  const del = useDeleteGroup()
  const [deleting, setDeleting] = React.useState(false)
  const [keep, setKeep] = React.useState(false)
  const files = g.files_path ? absTopicDir(ws, g.files_path) : null
  // A normal session of the project changes the group's files (no CLI command for it): its CLAUDE.md and group.json.
  const editWithClaude = () =>
    navigate(draftUrl(claudeTopic(ws, g.project), t('groups.claude.edit', { name: g.display_name, path: absTopicDir(ws, g.path) || g.path })))
  const newTopic = async () => {
    if (await confirm({ title: t('groups.reset.title'), description: t('groups.reset.desc'), confirmText: t('groups.reset.go') })) reset.mutate({ path: g.path })
  }
  return (
    <>
      <DropdownMenu>
        <Tooltip content={t('groups.menu')}>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('groups.menu')} data-testid="group-menu">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
        </Tooltip>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onEdit} data-testid="group-edit-open">
            <Pencil /> {t('common.edit')}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={editWithClaude} data-testid="group-edit-claude">
            <WandSparkles /> {t('agents.edit.button')}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={newTopic} data-testid="group-reset">
            <RotateCcw /> {t('groups.reset.item')}
          </DropdownMenuItem>
          {files && (
            <DropdownMenuItem onSelect={() => navigate(filesUrl(files))} data-testid="group-files">
              <FolderOpen /> {t('groups.files')}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem destructive onSelect={() => (setKeep(false), setDeleting(true))} data-testid="group-delete">
            <Trash2 /> {t('common.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={deleting} onOpenChange={setDeleting}>
        <DialogContent className="md:max-w-md" data-testid="group-delete-dialog">
          <DialogHeader>
            <DialogTitle>{t('groups.delete.title', { name: g.display_name })}</DialogTitle>
            <DialogDescription>{t('groups.delete.desc')}</DialogDescription>
          </DialogHeader>
          {g.shared_files && (
            <label className="flex items-start gap-2.5 text-sm pointer-coarse:min-h-10">
              <Checkbox checked={keep} onCheckedChange={(v) => setKeep(v === true)} className="mt-0.5" data-testid="group-delete-keep" />
              <span className="grid gap-0.5">
                <span>{t('groups.delete.keep')}</span>
                <span className="text-xs text-muted-foreground">{t('groups.delete.keepHint')}</span>
              </span>
            </label>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              loading={del.isPending}
              // mutateAsync: the page may be gone before a mutate() callback would run (its group left the cache)
              onClick={() => del.mutateAsync({ path: g.path, keep_files: keep }).then(() => (setDeleting(false), navigate('/agents')), () => {})}
              data-testid="group-delete-go"
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** The members under the header: face, name, role; the one speaking says so; a paused one is dimmed with "Let speak". */
function MemberBar({ group: g, onMention }: { group: AgentGroup; onMention: (slug: string) => void }) {
  const t = useT()
  const touch = useCompact()
  const navigate = useNavigate()
  const pause = useGroupPause()
  return (
    <div className="shrink-0 border-b px-3 py-2 md:px-8" data-testid="group-members">
      <div className={cn('mx-auto flex max-w-3xl gap-1.5', touch ? '-my-1 overflow-x-auto py-1' : 'flex-wrap')} data-hscroll-ok>
        {g.members.map((m) => {
          const ap = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(m.path)
          return (
            <span key={m.path} className={cn('flex shrink-0 items-center rounded-full border bg-card', m.speaking && 'border-primary/50 bg-primary/5')} data-testid="group-member" data-handle={m.handle} data-paused={m.paused || undefined}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn('flex min-w-0 items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-0.5 text-left outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring', touch && 'min-h-10 pl-1', (m.paused || !m.exists) && 'opacity-55')}
                    aria-label={m.display_name}
                  >
                    <AgentAvatarIcon avatar={m.avatar} size={touch ? 28 : 24} />
                    <span className="grid min-w-0 leading-tight">
                      <span className="flex items-center gap-1 text-[13px] font-medium">
                        <Sensitive length={6}>{m.display_name}</Sensitive>
                        {g.lead === m.path && <span className="text-[10px] font-normal text-muted-foreground">· {t('groups.lead')}</span>}
                      </span>
                      <span className="max-w-44 truncate text-[11px] text-muted-foreground">
                        {m.speaking ? (
                          <span className="text-primary">{t('groups.writingShort')}</span>
                        ) : !m.exists ? (
                          t('groups.member.gone')
                        ) : m.paused ? (
                          t('groups.member.paused')
                        ) : !m.enabled ? (
                          t('groups.member.off')
                        ) : (
                          <Sensitive length={10}>{m.role || `@${m.handle}`}</Sensitive>
                        )}
                      </span>
                    </span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onSelect={() => onMention(m.handle)} disabled={!m.exists}>
                    <AtSign /> {t('groups.member.mention', { slug: m.handle })}
                  </DropdownMenuItem>
                  {ap && m.exists && (
                    <DropdownMenuItem onSelect={() => navigate(agentRoute({ project: ap[1], topic: ap[2], name: ap[3] }))}>
                      <Bot /> {t('groups.member.open')}
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem onSelect={() => pause.mutate({ path: g.path, member: m.path, paused: !m.paused })} disabled={!m.exists} data-testid="group-member-pause">
                    {m.paused ? <Play /> : <Pause />} {m.paused ? t('groups.member.resume') : t('groups.member.pause')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              {m.paused && m.exists && (
                <Tooltip content={t('groups.member.resume')}>
                  <button
                    type="button"
                    onClick={() => pause.mutate({ path: g.path, member: m.path, paused: false })}
                    className="relative mr-1 grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground before:absolute before:-inset-2 before:content-['']"
                    aria-label={t('groups.member.resume')}
                    data-testid="group-member-resume"
                  >
                    <Play className="size-3" />
                  </button>
                </Tooltip>
              )}
            </span>
          )
        })}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- The conversation */
function Conversation({ group: g, composer }: { group: AgentGroup; composer: React.Ref<ComposerApi> }) {
  const t = useT()
  const { data, isLoading, error } = useGroupMessages(g.path)
  const { data: ws } = useWorkspace()
  const seen = useGroupSeen()
  const box = React.useRef<HTMLDivElement>(null)
  const msgs = React.useMemo(() => data || [], [data])
  const byPath = React.useMemo(() => new Map(g.members.map((m) => [m.path, m])), [g.members])
  const names = useMentionMap(g.members)
  const said = msgs.some((m) => m.kind === 'message')
  const last = msgs[msgs.length - 1]?.id
  // Newest at the bottom: follow it when a message arrives (unless the user scrolled up to read).
  const stick = React.useRef(true)
  React.useLayoutEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [last, g.speaking])
  // Reading the page = the group is read (again when an answer comes in while it is open).
  const seenMutate = seen.mutate
  React.useEffect(() => {
    if (g.unread > 0) seenMutate({ path: g.path })
  }, [g.unread, g.path, seenMutate])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className="min-h-0 flex-1 overflow-y-auto"
        aria-live="polite"
        data-testid="group-thread"
      >
        <div className="mx-auto grid max-w-3xl content-start gap-3 px-4 py-5 md:px-8">
          {isLoading ? (
            [0, 1, 2].map((i) => <Skeleton key={i} className={cn('h-16 rounded-xl', i % 2 && 'ml-10')} />)
          ) : error ? (
            <EmptyState tone="error" compact title={t('groups.thread.error')} description={errorMessage(error)} />
          ) : (
            <>
              {!said && <HowItWorks group={g} />}
              {msgs.map((m) => (
                <GroupMessage key={m.id} m={m} member={byPath.get(m.author)} root={ws?.root} names={names} />
              ))}
            </>
          )}
          {g.speaking && <Speaking group={g} />}
        </div>
      </div>
      <Composer group={g} ref={composer} first={!said} />
    </div>
  )
}

/** Before the first message: how a group works, in three lines, and an example with its members' names. */
function HowItWorks({ group: g }: { group: AgentGroup }) {
  const t = useT()
  const [a, b] = g.members.map((m) => m.handle)
  return (
    <div className="grid gap-2 rounded-xl border border-dashed px-4 py-3 text-sm" data-testid="group-empty">
      <p className="flex items-center gap-2 font-medium">
        <UsersRound className="size-4 text-muted-foreground" /> {t('groups.empty.title')}
      </p>
      <ul className="grid gap-1 text-muted-foreground">
        <li>{t('groups.empty.line1')}</li>
        <li>{t('groups.empty.line2')}</li>
        <li>{t('groups.empty.line3')}</li>
      </ul>
      {/* No goal yet (a quick creation): the first message can say what the group is for. */}
      {!g.goal.trim() && <p className="font-medium text-foreground">{t('groups.empty.goal')}</p>}
      <p className="text-xs text-muted-foreground">
        {t('groups.empty.example')}{' '}
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">
          <Sensitive>{t(g.goal.trim() ? 'groups.empty.exampleText' : 'groups.empty.goalExample', { a: a || 'writer', b: b || 'reviewer' })}</Sensitive>
        </code>
      </p>
    </div>
  )
}

/** The member speaking now: "writing…" with a link to its turn, or its request for approval (Allow / Deny here). */
function Speaking({ group: g }: { group: AgentGroup }) {
  const t = useT()
  const m = g.members.find((x) => x.path === g.speaking)
  const { data: agents } = useAgents()
  const a = agents?.agents.find((x) => x.path === g.speaking)
  const waiting = (a?.waiting || 0) > 0
  const { data: pending } = usePendingApprovals(waiting)
  const sid = g.speaking_session || undefined
  // A member speaks one turn at a time in the group: its requests waiting now (of this turn when its session is known).
  const asks: Approval[] = React.useMemo(
    () => (pending || []).filter((x) => x.agent_path === g.speaking && x.status === 'pending' && (!sid || x.session === sid)),
    [pending, g.speaking, sid],
  )
  if (!m) return null
  return (
    <div className="flex items-start gap-2" data-kind="speaking" data-testid="group-speaking">
      <AgentAvatarIcon avatar={m.avatar} size={32} animate />
      <div className={cn('grid min-w-0 gap-1.5 rounded-xl rounded-tl-sm border bg-card px-3 py-2 text-sm', asks.length > 0 && 'flex-1 border-warning/40 bg-warning/5')}>
        <span className="flex items-center gap-2 text-muted-foreground">
          {asks.length || waiting ? <ShieldCheck className="size-4 text-warning" /> : <StatusDot tone="running" pulse className="size-2" />}
          {asks.length || waiting ? t('agents.conv.waiting', { name: m.display_name }) : t('groups.writing', { name: m.display_name })}
        </span>
        {asks.map((x) => (
          <ApprovalCard key={x.id} approval={x} className="shadow-none" />
        ))}
        {sid && (
          <Link to={agentRunRoute(m.path, sid)} className="inline-flex items-center gap-1 text-xs text-primary hover:underline pointer-coarse:min-h-10" data-testid="group-follow">
            <PlayCircle className="size-3" /> {t('agents.conv.follow')}
          </Link>
        )}
      </div>
    </div>
  )
}

/** A system line (note, stop) in words of the UI language when it is one the server writes. */
function noteText(t: TFn, m: AgentGroupMessage): string {
  if (m.kind === 'stop') return t('groups.note.stopped')
  if (m.reset) return t('groups.note.reset')
  if (m.limit === 'waves' || m.limit === 'replies' || m.limit === 'per_hour') {
    const count = Number(/(\d+)/.exec(m.text)?.[1] || 0)
    return t(`groups.note.limit.${m.limit}` as 'groups.note.limit.waves', { count })
  }
  if (m.text === 'Group created') return t('groups.note.created')
  return m.text
}

/** Why a member could not speak: the agent's reasons (switched off, budget...), a failed turn, else the server's text. */
function skipText(t: TFn, m: AgentGroupMessage): string {
  const known = reasonText(t, m.reason)
  if (known && known !== m.reason) return known
  if (m.reason === 'failed') return t('groups.skip.failed')
  return m.text.replace(/^@[a-z0-9-]+:\s*/i, '')
}

function GroupMessage({ m, member, root, names }: { m: AgentGroupMessage; member?: AgentGroupMember; root?: string; names: MentionMap }) {
  const t = useT()
  const lang = useLang()
  const chips = React.useMemo(() => mentionComponents(names), [names])
  const [open, setOpen] = React.useState(false)
  const when = (
    <time className="text-[11px] text-muted-foreground tabular-nums" dateTime={new Date(m.at * 1000).toISOString()} title={fmtDate(m.at, lang)}>
      {fmtRelative(m.at, lang)}
    </time>
  )
  const who = member?.display_name || slugOf(m.author)
  const run = m.session && m.author && m.author !== 'me' && (
    <Link to={agentRunRoute(m.author, m.session)} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10" data-testid="group-open-run">
      <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
    </Link>
  )
  if (m.kind === 'note' || m.kind === 'stop')
    return (
      <div className={cn('flex items-center justify-center gap-2 py-1 text-center text-xs text-muted-foreground', m.limit && 'text-warning')} data-kind={m.kind}>
        <span className="h-px w-6 shrink-0 bg-border" aria-hidden />
        <span>
          {noteText(t, m)} · {when}
        </span>
        <span className="h-px w-6 shrink-0 bg-border" aria-hidden />
      </div>
    )
  if (m.kind === 'pass')
    return (
      <div className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground" data-kind="pass">
        {member && <AgentAvatarIcon avatar={member.avatar} size={16} />}
        <span>
          {t('groups.pass', { name: who })} · {when}
        </span>
        {run}
      </div>
    )
  if (m.kind === 'skip')
    return (
      <div className="flex items-center justify-center gap-1.5 text-center text-xs text-warning" data-kind="skip">
        {member && <AgentAvatarIcon avatar={member.avatar} size={16} />}
        <span>
          {t('groups.skip', { name: who })} <span className="text-muted-foreground">{skipText(t, m)}</span> · {when}
        </span>
      </div>
    )
  if (m.author === 'me')
    return (
      <div className="ml-auto grid w-fit max-w-[85%] gap-1 max-sm:max-w-full" data-kind="mine">
        <div className="rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
          <p className="whitespace-pre-wrap break-words">
            <Sensitive block>{mentionNodes(m.text, names, 'primary')}</Sensitive>
          </p>
        </div>
        <span className="flex justify-end text-[11px] text-muted-foreground">{when}</span>
      </div>
    )
  const long = (m.text || '').length > FOLD_CHARS
  return (
    <div className="flex items-start gap-2" data-kind="answer" data-author={slugOf(m.author)}>
      <AgentAvatarIcon avatar={member?.avatar} size={32} />
      <div className="grid min-w-0 max-w-[85%] gap-1.5 rounded-xl rounded-tl-sm border bg-card px-3 py-2 max-sm:max-w-full">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
          <span className="font-medium">
            <Sensitive length={8}>{who}</Sensitive>
          </span>
          {member?.role && (
            <span className="max-w-48 truncate text-muted-foreground">
              <Sensitive length={8}>{member.role}</Sensitive>
            </span>
          )}
          {when}
          {m.cost != null && m.cost > 0 && <span className="text-muted-foreground tabular-nums">· {fmtCost(m.cost)}</span>}
        </div>
        <div className={cn('relative min-w-0 text-sm', long && !open && 'max-h-64 overflow-hidden')}>
          <Sensitive block>
            <React.Suspense fallback={<p className="whitespace-pre-wrap break-words">{m.text}</p>}>
              <Markdown className="text-sm" components={chips}>
                {linkifyMarkdown(m.text, root)}
              </Markdown>
            </React.Suspense>
          </Sensitive>
          {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card" aria-hidden />}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 empty:hidden">
          {long && (
            <button type="button" className="text-xs text-primary hover:underline pointer-coarse:min-h-10" onClick={() => setOpen((o) => !o)}>
              {open ? t('agents.conv.readLess') : t('agents.conv.readMore')}
            </button>
          )}
          {run}
        </div>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- The box */
export type ComposerApi = { mention: (slug: string) => void }

/** The `@word` being typed just before the caret (start of the text or after a space / bracket), else null. */
function mentionAt(text: string, caret: number): { start: number; q: string } | null {
  const m = /(^|[\s(])@([\p{L}0-9-]*)$/iu.exec(text.slice(0, caret))
  return m ? { start: caret - m[2].length - 1, q: m[2].toLowerCase() } : null
}

/** Lower case without accents: « réd » finds « Rédacteur » and @redacteur. */
const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()

type MentionPick = { slug: string; label: string; member?: AgentGroupMember }

/** `first`: nothing said yet (the placeholder invites to say what the group is for when it has no goal). Opened right
 *  after its creation (router state `focus`), the box has the focus. */
function Composer({ group: g, ref, first }: { group: AgentGroup; ref?: React.Ref<ComposerApi>; first?: boolean }) {
  const t = useT()
  const touch = useCompact()
  const say = useGroupSay()
  const [text, setText] = React.useState('')
  const [caret, setCaret] = React.useState(0)
  const [hi, setHi] = React.useState(0)
  const [closed, setClosed] = React.useState(false)
  const input = React.useRef<HTMLTextAreaElement>(null)
  const location = useLocation()
  const focus = !!(location.state as { focus?: boolean } | null)?.focus
  React.useEffect(() => {
    if (focus) input.current?.focus()
  }, [focus])
  const ready = g.members.filter((m) => m.exists).length >= 2
  const names = useMentionMap(g.members)
  const to = namedIn(text, names, g.members.filter((m) => m.exists))

  const at = mentionAt(text, caret)
  // The members (and @all) whose @name or name starts with what is typed, then the ones that contain it.
  const picks: MentionPick[] = (() => {
    if (!at) return []
    const all: MentionPick[] = [
      ...g.members.filter((m) => m.exists).map((m) => ({ slug: m.handle, label: m.display_name, member: m })),
      { slug: 'all', label: t('groups.mention.all') },
    ]
    const q = fold(at.q)
    const starts = all.filter((p) => p.slug.startsWith(q) || fold(p.label).startsWith(q))
    const inside = all.filter((p) => !starts.includes(p) && (p.slug.includes(q) || fold(p.label).includes(q)))
    return [...starts, ...inside]
  })()
  const popup = !closed && !!at && picks.length > 0
  React.useEffect(() => setHi(0), [at?.q])

  /** Put `@slug ` in place of the `@word` being typed (or at the caret / the end), the caret after it. */
  const insert = (slug: string, from?: number, to?: number) => {
    const el = input.current
    const end = to ?? el?.selectionEnd ?? text.length
    const start = from ?? end
    const before = text.slice(0, start)
    const lead = from === undefined && before && !/\s$/.test(before) ? ' ' : ''
    const next = `${before}${lead}@${slug} ${text.slice(end)}`
    const pos = start + lead.length + slug.length + 2
    setText(next)
    setCaret(pos)
    setClosed(false)
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(pos, pos)
    })
  }
  React.useImperativeHandle(ref, () => ({ mention: (slug: string) => insert(slug) }))
  const pick = (p: MentionPick) => at && insert(p.slug, at.start, caret)

  const submit = () => {
    const v = text.trim()
    if (!v || !ready || say.isPending) return
    setText('')
    setCaret(0)
    say.mutate({ path: g.path, text: v }, { onError: () => setText(v) })
  }
  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return
    if (popup) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        setHi((i) => (i + (e.key === 'ArrowDown' ? 1 : picks.length - 1)) % picks.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        pick(picks[Math.min(hi, picks.length - 1)])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setClosed(true)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
  const track = (e: React.SyntheticEvent<HTMLTextAreaElement>) => setCaret(e.currentTarget.selectionStart ?? 0)

  return (
    <div className="shrink-0 border-t bg-background px-3 py-3 md:px-8">
      <div className="relative mx-auto flex max-w-3xl flex-col rounded-xl border bg-card p-1.5 focus-within:border-primary/50">
        {popup && (
          <div role="listbox" aria-label={t('groups.mention.title')} className="absolute inset-x-0 bottom-full z-20 mb-1.5 grid max-h-64 gap-0.5 overflow-y-auto rounded-xl border bg-popover p-1 shadow-lg" data-testid="group-mention-list">
            {picks.map((p, i) => (
              <button
                key={p.slug}
                type="button"
                role="option"
                aria-selected={i === hi}
                // keep the focus (and the caret) in the box
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(p)}
                onMouseEnter={() => setHi(i)}
                className={cn('flex min-w-0 items-center gap-2 rounded-lg px-2 text-left text-sm', touch ? 'min-h-11' : 'h-9', i === hi && 'bg-accent')}
                data-slug={p.slug}
              >
                {p.member ? <AgentAvatarIcon avatar={p.member.avatar} size={22} /> : <span className="grid size-[22px] place-items-center rounded-md bg-muted"><UsersRound className="size-3.5 text-muted-foreground" /></span>}
                <span className="min-w-0 truncate font-medium">
                  <Sensitive length={6}>{p.label}</Sensitive>
                </span>
                <span className="shrink-0 font-mono text-xs text-muted-foreground">@{p.slug}</span>
                {p.member?.paused && <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{t('groups.member.paused')}</span>}
              </button>
            ))}
          </div>
        )}
        {!ready ? (
          <p className="px-2 py-1.5 text-sm text-muted-foreground" data-testid="group-not-ready">
            {t('groups.notReady')}
          </p>
        ) : (
          <>
          {to.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 px-1.5 pt-1 text-xs text-muted-foreground" data-testid="group-to">
              <span>{t('groups.to')}</span>
              {to.map((m) => (
                <MentionChip key={m.path} member={m} handle={m.handle} />
              ))}
            </div>
          )}
          <div className="flex items-end gap-1">
            <Textarea
              ref={input}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setCaret(e.target.selectionStart ?? e.target.value.length)
                setClosed(false)
              }}
              onKeyDown={onKey}
              onSelect={track}
              onClick={track}
              onBlur={() => setClosed(true)}
              onFocus={() => setClosed(false)}
              minRows={1}
              maxRows={8}
              placeholder={first && !g.goal.trim() ? t('groups.placeholderGoal') : t('groups.placeholder')}
              aria-label={t('groups.placeholder')}
              aria-expanded={popup}
              aria-autocomplete="list"
              className="min-h-8 flex-1 resize-none border-0 bg-transparent px-1.5 py-1.5 text-[14px] shadow-none focus-visible:ring-0 dark:bg-transparent"
              data-testid="group-text"
            />
            <Button size="icon-sm" onClick={submit} disabled={!text.trim()} loading={say.isPending} aria-label={t('groups.send')} data-testid="group-send">
              <Send />
            </Button>
          </div>
          </>
        )}
      </div>
    </div>
  )
}
