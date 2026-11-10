// One agent (/agents/<project>/<topic>/<name>) as a conversation, like a contact in a chat app:
// - the thread fills the page: what started each run (an event, a schedule, your message), the agent's results
//   (long ones folded), a "working…" bubble per running session, a callout when it waits for your OK;
// - the box at the bottom writes to it: a new message starts a new session (the server adds its last results as
//   context), "Reply" on a result goes on with that result's session (same context, same session);
// - its profile on the right (a sheet on a phone): role edited in place, "When it works" (triggers as sentences,
//   webhook address, what came in, test), guards, memory, advanced settings (a sheet), "Edit with Claude" (a session
//   of its topic configures it: an agent cannot change its own role or settings).
// Opening the page marks its results as read (POST /seen). Its runs open in place (RunView), never in Sessions.
import * as React from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  AlertTriangle, ArrowLeft, Bot, CheckCircle2, ExternalLink, Info, KeyRound, Lock, MessageSquarePlus, Pencil, PlayCircle, Reply, Send, Settings2, ShieldCheck, StickyNote, UsersRound, X, XCircle,
} from 'lucide-react'
import { useLang, useT, type TFn } from '@/i18n'
import { errorMessage } from '@/lib/api'
import {
  agentRunRoute, useAgent, useAgentSandbox, useAgentSeen, useAgentThread, useCrons, useFileContent, useNewAgentChat, usePatchAgent, useRunAgent, useWorkspace, useWriteFile,
} from '@/lib/queries'
import type { AgentDetail, AgentMessage, Approval, Cron } from '@/lib/types'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCompact, useMediaQuery } from '@/stores/media'
import {
  Badge, Button, EmptyState, Sensitive, Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle, Skeleton, StatusDot, Switch, Textarea, Tooltip, toast,
} from '@/components/ui'
import { Page, PageHeader } from '@/components/shell/Page'
import { absTopicDir, filesUrl, fmtCost } from '@/pages/sessions/util'
import { AgentAvatarIcon } from './Avatar'
import { AgentTriggers } from './AgentTriggers'
import { AgentSettings, type SectionId } from './AgentSettings'
import { EditWithClaude } from './EditWithClaude'
import { ProfileHead } from './Appearance'
import { AgentsOff, ContinueButton, costLine, reasonText, useAgentsOn } from './parts'
import { ThreadApprovalBody, useThreadApprovals } from './approvals'
import { AttachButton, AttachList, bringBackDraft, insertAtCaret, useAttachments, useDraftText, withQuote } from './attach'
import { QuotePill } from '@/pages/sessions/Quote'
import { agentDraftKey } from '@/lib/drafts'
import { VoiceButton } from '@/features/voice/VoiceButton'
import { AttachmentStrip, MessageMedia, useMessageMenu } from '@/pages/sessions/Items'
import { AnswerContext, AnswerText } from './answer'
import { useSessionLog } from '@/pages/sessions/log'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))
/** The memory is the agent's own writing: no picture of this site loads without a click (Markdown localImage). */
const clickToLoad = () => null

/** A result longer than this is folded (the first lines and "Read all"). */
const FOLD_CHARS = 700
/** Who wrote a run: the user (a message) or something else (an event, a schedule, another agent). */
const isMine = (m: AgentMessage) => m.trigger === 'manual' || m.trigger === 'telegram' || m.source === 'manual' || m.source === 'telegram'

/** `at`: the agent when the route's names say something else (an agent of a project called "groups", whose address
 *  looks like a group's: AgentsLayout hands it over). */
export default function AgentPage({ at }: { at?: { project: string; topic: string; name: string } } = {}) {
  const t = useT()
  const on = useAgentsOn()
  const params = useParams()
  const { project = '', topic = '', name = '' } = at || params
  const path = `projects/${project}/topics/${topic}/agents/${name}`
  const { data: a, isLoading, error, refetch } = useAgent(on === false ? null : path)
  // The profile can sit on the right of the conversation when there is room next to the list of agents: shown by
  // default from 1600 px, folded below (the conversation would be narrower than a phone); "Profile" folds / unfolds
  // it, remembered in this browser. Narrower: a sheet.
  const dockable = useMediaQuery('(min-width: 1280px)')
  const roomy = useMediaQuery('(min-width: 1600px)')
  const [docked, setDocked] = useDockedProfile()
  const wide = dockable && (docked ?? roomy)
  const touch = useCompact()
  const [profile, setProfile] = React.useState(false)
  const openProfile = () => (dockable ? setDocked(!wide) : setProfile(true))
  // ?settings=<section> (a link from the E-mail page): the profile opens, then its settings on that section
  const [search] = useSearchParams()
  const wantSettings = !!search.get('settings') && !!a
  React.useEffect(() => {
    if (wantSettings && !wide) {
      if (dockable) setDocked(true)
      else setProfile(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantSettings])
  // On a phone the agent is full screen: back to the list (on a computer the list stays on the left).
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
        <Skeleton className="h-16 rounded-xl" />
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

  const running = (a.running_now || 0) > 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        leading={
          <div className="flex items-center gap-2">
            {back}
            <button type="button" onClick={() => !wide && openProfile()} className={cn('relative shrink-0 before:absolute before:-inset-1 before:content-[""]', wide && 'cursor-default')} aria-label={t('agents.panel.open')}>
              <AgentAvatarIcon avatar={a.avatar} size={32} />
              {running && <StatusDot tone="running" pulse label={t('agents.runningNow')} className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full ring-2 ring-background sm:hidden" />}
            </button>
          </div>
        }
        title={
          // On a phone the name keeps the room: "Running now" is a dot on the avatar there.
          <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 truncate">
              <Sensitive length={8}>{a.display_name}</Sensitive>
            </span>
            {running ? (
              <Badge variant="default" className="shrink-0 gap-1 max-sm:hidden">
                <StatusDot tone="running" pulse className="size-1.5" /> {t('agents.runningNow')}
              </Badge>
            ) : (
              !a.enabled && <Badge variant="muted">{t('agents.paused')}</Badge>
            )}
          </span>
        }
        description={
          <Link to={`/sessions?path=${encodeURIComponent(`projects/${a.project}/topics/${a.topic}`)}`} className="hover:text-foreground hover:underline">
            <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
          </Link>
        }
        actions={
          <>
            <Tooltip content={a.enabled ? t('agents.switchOff') : t('agents.switchOn')}>
              <span className="flex items-center">
                <EnabledSwitch agent={a} />
              </span>
            </Tooltip>
            {/* Phone: in the profile only (its "Edit with Claude" row), the header leaves the room to the name. */}
            <span className="contents max-sm:hidden">
              <EditWithClaude agent={a} />
            </span>
            <Button variant={wide ? 'secondary' : 'outline'} size="sm" onClick={openProfile} aria-pressed={dockable ? wide : undefined} data-testid="agent-profile-open">
              <Info /> <span className="max-sm:sr-only">{t('agents.panel.open')}</span>
            </Button>
          </>
        }
      />
      <div className="flex min-h-0 flex-1">
        {/* keyed: a reply started on one agent never goes with a message to another */}
        <Conversation key={a.path} agent={a} />
        {wide && (
          <aside className="w-[360px] shrink-0 overflow-y-auto border-l" data-testid="agent-profile">
            <Profile agent={a} />
          </aside>
        )}
      </div>
      {!dockable && (
        <Sheet open={profile} onOpenChange={setProfile}>
          <SheetContent side="right" data-testid="agent-profile">
            <SheetHeader>
              <SheetTitle>{t('agents.panel.open')}</SheetTitle>
            </SheetHeader>
            <SheetBody className="p-0">
              <Profile agent={a} />
            </SheetBody>
          </SheetContent>
        </Sheet>
      )}
    </div>
  )
}

const DOCK_KEY = 'mx-agent-profile'

/** The user's choice for the profile column on a computer: shown, folded, or null (the default for the width). */
function useDockedProfile(): [boolean | null, (v: boolean) => void] {
  const read = () => {
    try {
      const v = localStorage.getItem(DOCK_KEY)
      return v === 'shown' ? true : v === 'folded' ? false : null
    } catch {
      return null
    }
  }
  const [docked, setState] = React.useState<boolean | null>(read)
  const set = React.useCallback((v: boolean) => {
    setState(v)
    try {
      localStorage.setItem(DOCK_KEY, v ? 'shown' : 'folded')
    } catch {
      /* private mode: this page only */
    }
  }, [])
  return [docked, set]
}

function EnabledSwitch({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  return (
    <Switch
      checked={a.enabled}
      onCheckedChange={(v) => patch.mutate({ path: a.path, enabled: v })}
      aria-label={a.enabled ? t('agents.switchOff') : t('agents.switchOn')}
      data-testid="agent-enabled"
    />
  )
}

/* ---------------------------------------------------------------- The conversation */
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

function Conversation({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data, isLoading, error } = useAgentThread(a.path)
  const { data: crons } = useCrons()
  const seen = useAgentSeen()
  const box = React.useRef<HTMLDivElement>(null)
  const composer = React.useRef<AgentComposerApi>(null)
  const [replyTo, setReplyTo] = React.useState<AgentMessage | null>(null)
  const msgs = React.useMemo(() => data?.messages || [], [data])
  const byId = React.useMemo(() => new Map(msgs.map((m) => [m.id, m])), [msgs])
  const asks = useThreadApprovals(a.path, msgs)
  const last = msgs[msgs.length - 1]?.id
  // Newest at the bottom: follow it when a message arrives (unless the user scrolled up to read).
  const stick = React.useRef(true)
  React.useLayoutEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [last, a.running_now])
  // Reading the page = its results are read (again when a new one comes in while it is open).
  const unread = a.thread_unread || 0
  const seenMutate = seen.mutate
  React.useEffect(() => {
    if (unread > 0) seenMutate({ path: a.path })
  }, [unread, a.path, seenMutate])

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className="min-h-0 flex-1 overflow-y-auto"
        aria-live="polite"
        data-testid="agent-thread"
        data-thread
      >
        <AnswerContext owner={{ agent: a.path }}>
          <div className="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] content-start gap-3 px-4 py-5 md:px-8">
            {isLoading ? (
              [0, 1, 2].map((i) => <Skeleton key={i} className={cn('h-16 rounded-xl', i % 2 && 'ml-10')} />)
            ) : error ? (
              <EmptyState tone="error" compact title={t('agents.thread.error')} description={errorMessage(error)} />
            ) : !msgs.length ? (
              <EmptyState icon={StickyNote} compact title={t('agents.thread.empty')} description={t('agents.thread.emptyDesc')} />
            ) : (
              msgs
                .filter((m) => !asks.merged(m))
                .map((m, i, shown) => (
                  <React.Fragment key={m.id}>
                    {m.chat === 'new' && newChatLine(shown, i) && <ChatLine />}
                    <ThreadMessage
                      m={m}
                      agent={a}
                      crons={crons?.jobs || []}
                      answers={m.reply_to ? byId.get(m.reply_to) : undefined}
                      onReply={setReplyTo}
                      live={m.kind === 'approval' && m.approval ? asks.live.get(m.approval) : undefined}
                      decided={m.kind === 'approval' && m.approval ? asks.decided.get(m.approval) : undefined}
                    />
                  </React.Fragment>
                ))
            )}
            {(a.running_sessions || []).map((s) => (
              <Working key={s.id} agent={a} sid={s.id} waiting={(a.waiting || 0) > 0} />
            ))}
          </div>
        </AnswerContext>
      </div>
      <QuotePill scope={box} selector="[data-quote]" onQuote={(q, el) => composer.current?.quote(q, isOwnRun(el) ? null : a.display_name)} />
      <Composer key={a.path} ref={composer} agent={a} replyTo={replyTo} onCancelReply={() => setReplyTo(null)} />
    </div>
  )
}

/** A new conversation begins here: drawn unless it is the very first message or the "New conversation" note
 *  (the button) is just above. */
function newChatLine(msgs: AgentMessage[], i: number): boolean {
  const before = msgs.slice(0, i).filter((m) => m.kind !== 'note' || m.status === 'new_chat')
  return before.length > 0 && before[before.length - 1].status !== 'new_chat'
}

function ChatLine() {
  const t = useT()
  return (
    <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground" data-kind="new-chat">
      <span className="h-px flex-1 bg-border" aria-hidden />
      <MessageSquarePlus className="size-3.5" /> {t('agents.chat.started')}
      <span className="h-px flex-1 bg-border" aria-hidden />
    </div>
  )
}

/** What the agent is writing in this turn (after the last message it got), and the tool it is using now. */
function useLiveTurn(sid: string): { text: string; tool: string } {
  const log = useSessionLog(sid)
  return React.useMemo(() => {
    let text = ''
    let tool = ''
    for (let i = log.items.length - 1; i >= 0; i--) {
      const it = log.items[i]
      if (it.kind === 'user') break
      if (it.kind === 'assistant' && !text) text = it.ev.text || ''
      if (it.kind === 'tool' && !text && !tool && !it.result) tool = it.use.summary || it.use.name
    }
    return { text, tool }
  }, [log.items])
}

/** A running session of the agent: "working…" with what it writes as it comes, or "waiting for your OK" with the
 *  way to answer. */
function Working({ agent: a, sid, waiting }: { agent: AgentDetail; sid: string; waiting: boolean }) {
  const t = useT()
  const live = useLiveTurn(sid)
  return (
    <div className="flex items-start gap-2" data-kind="working">
      <AgentAvatarIcon avatar={a.avatar} size={32} />
      <div className={cn('grid min-w-0 gap-1 rounded-xl rounded-tl-sm border bg-card px-3 py-2 text-sm', waiting && 'border-warning/40 bg-warning/5')}>
        <span className="flex items-center gap-2 text-muted-foreground wrap-anywhere">
          {waiting ? <ShieldCheck className="size-4 text-warning" /> : <StatusDot tone="running" pulse className="size-2" />}
          {waiting ? t('agents.conv.waiting', { name: a.display_name }) : t('agents.conv.working', { name: a.display_name })}
        </span>
        {!waiting && live.text && (
          <div className="min-w-0 text-sm" data-testid="agent-live-text">
            <Sensitive block>
              <AnswerText text={live.text} />
            </Sensitive>
          </div>
        )}
        {!waiting && live.tool && (
          <span className="truncate font-mono text-[11px] text-muted-foreground" data-testid="agent-live-tool">
            <Sensitive>{live.tool}</Sensitive>
          </span>
        )}
        <Link to={agentRunRoute(a.path, sid)} className="inline-flex items-center gap-1 text-xs text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-follow">
          <PlayCircle className="size-3" /> {waiting ? t('agents.conv.waitingOpen') : t('agents.conv.follow')}
        </Link>
      </div>
    </div>
  )
}

function ThreadMessage({
  m, agent: a, crons, answers, onReply, live, decided,
}: {
  m: AgentMessage
  agent: AgentDetail
  crons: Cron[]
  answers?: AgentMessage
  onReply: (m: AgentMessage) => void
  /** approval: the request while it waits (Allow / Deny), then its note (what was decided) */
  live?: Approval
  decided?: AgentMessage
}) {
  const t = useT()
  const lang = useLang()
  const [open, setOpen] = React.useState(false)
  // Right click (long press): copy what was said, mine or the agent's (not the approvals: their buttons are the point).
  const { onContextMenu, touch, menu } = useMessageMenu({ text: m.kind === 'approval' ? '' : m.text, copy: true })
  const when = (
    <time className="text-[11px] text-muted-foreground tabular-nums" dateTime={new Date(m.at * 1000).toISOString()} title={fmtDate(m.at, lang)}>
      {fmtRelative(m.at, lang)}
    </time>
  )
  const sessionLink = m.session && (
    <Link to={agentRunRoute(a.path, m.session)} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-open-run">
      <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
    </Link>
  )
  const quote = answers && (
    <p className="flex min-w-0 items-center gap-1 text-[11px] text-muted-foreground">
      <Reply className="size-3 shrink-0" />
      <span className="truncate">{t('agents.conv.inReply', { text: firstLine(answers.text) })}</span>
    </p>
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
  if (m.kind === 'run') {
    if (isMine(m))
      return (
        <div className="ml-auto grid w-fit min-w-0 max-w-[85%] gap-1 max-sm:max-w-full" data-kind="run">
          {quote}
          {!!m.attachments?.length && <AttachmentStrip paths={m.attachments} />}
          <div className="relative rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground" onContextMenu={onContextMenu} {...touch}>
            {menu}
            <p className="whitespace-pre-wrap break-words" data-quote>
              <Sensitive block>{m.text || t('agents.conv.routine')}</Sensitive>
            </p>
          </div>
          <span className="flex justify-end gap-2 text-[11px] text-muted-foreground">
            {m.trigger === 'telegram' && t('agents.from.telegram')} {when}
          </span>
        </div>
      )
    return (
      <div className="grid gap-1 rounded-xl border border-dashed px-3 py-2 text-sm sm:ml-9" data-kind="run">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className="min-w-0 font-medium text-foreground wrap-anywhere">{t('agents.thread.started', { from: triggerLabel(t, m, crons) })}</span>
          {when}
        </div>
        {m.text && (
          <p className="line-clamp-4 whitespace-pre-wrap break-words text-muted-foreground">
            <Sensitive block>{m.text}</Sensitive>
          </p>
        )}
        {!!m.attachments?.length && (
          <div className="flex">
            <AttachmentStrip paths={m.attachments} />
          </div>
        )}
      </div>
    )
  }
  // result / approval: the agent speaks
  const failed = m.kind === 'result' && m.ok === false
  const long = (m.text || '').length > FOLD_CHARS
  return (
    <div className="flex items-start gap-2" data-kind={m.kind}>
      <AgentAvatarIcon avatar={a.avatar} size={32} />
      <div
        onContextMenu={onContextMenu}
        {...touch}
        className={cn('relative grid min-w-0 max-w-[85%] gap-1.5 rounded-xl rounded-tl-sm border bg-card px-3 py-2 max-sm:max-w-full', failed && 'border-destructive/40', m.kind === 'approval' && live && 'border-warning/40 bg-warning/5', m.kind === 'approval' && live && 'max-w-full flex-1')}
      >
        {menu}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
          <span className="min-w-0 font-medium wrap-anywhere">
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          {m.kind === 'approval' ? (
            !live && <Badge variant="secondary">{t('agents.approval.asked')}</Badge>
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
        {m.kind === 'approval' ? (
          <ThreadApprovalBody m={m} live={live} decided={decided} />
        ) : m.text ? (
          <div className="grid min-w-0">
            <div className={cn('relative min-w-0 text-sm', long && !open && 'max-h-64 overflow-hidden')} data-quote>
              <Sensitive block>
                <AnswerText text={m.text} />
              </Sensitive>
              {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card" aria-hidden />}
            </div>
            <Sensitive block>
              <MessageMedia text={m.text} />
            </Sensitive>
          </div>
        ) : (
          <span className="text-sm text-muted-foreground italic">{t('agents.thread.noText')}</span>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {long && (
            <button type="button" className="text-xs text-primary hover:underline pointer-coarse:min-h-10" onClick={() => setOpen((o) => !o)}>
              {open ? t('agents.conv.readLess') : t('agents.conv.readMore')}
            </button>
          )}
          {m.kind === 'result' && m.session && m.session !== a.chat_session && (
            <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary pointer-coarse:min-h-10" onClick={() => onReply(m)} data-testid="agent-reply">
              <Reply className="size-3" /> {t('agents.conv.reply')}
            </button>
          )}
          {sessionLink}
          {m.kind === 'result' && m.session && <ContinueButton agent={a} sid={m.session} variant="link" />}
        </div>
      </div>
    </div>
  )
}

const firstLine = (s: string) => (s || '').replace(/^[#>*\s-]+/, '').split('\n')[0].slice(0, 90)

/** A message of the owner (a run he started, right-aligned), not something the agent wrote. */
const isOwnRun = (el: Element) => {
  const m = el.closest('[data-kind]')
  return m?.getAttribute('data-kind') === 'run' && m.classList.contains('ml-auto')
}

/** What the conversation hands to the box: a quoted selection (`from`: the agent that wrote it, null = the owner). */
type AgentComposerApi = { quote: (text: string, from: string | null) => void }

function Composer({ agent: a, replyTo, onCancelReply, ref }: { agent: AgentDetail; replyTo: AgentMessage | null; onCancelReply: () => void; ref?: React.Ref<AgentComposerApi> }) {
  const t = useT()
  const run = useRunAgent()
  const fresh = useNewAgentChat()
  const key = agentDraftKey('agent', a.path)
  const { text, setText } = useDraftText(key)
  const input = React.useRef<HTMLTextAreaElement>(null)
  // The caret goes to `placeAt` as soon as the new text is in the box (before the next key is typed).
  const placeAt = React.useRef<number | null>(null)
  const putText = (pasted: string, start: number, end: number) =>
    setText((cur) => {
      const from = Math.min(start, cur.length)
      placeAt.current = from + pasted.length
      return cur.slice(0, from) + pasted + cur.slice(Math.min(end, cur.length))
    })
  React.useLayoutEffect(() => {
    const el = input.current
    if (placeAt.current == null || !el) return
    el.focus()
    el.setSelectionRange(placeAt.current, placeAt.current)
    placeAt.current = null
  }, [text])
  const files = useAttachments(a.path, undefined, { draftKey: key, putText })
  React.useEffect(() => {
    if (replyTo) input.current?.focus()
  }, [replyTo])
  /** Caret after `next` once it is in the box. */
  const caretTo = (pos: number) =>
    requestAnimationFrame(() => {
      input.current?.focus({ preventScroll: true })
      input.current?.setSelectionRange(pos, pos)
    })
  // A selection quoted from the conversation: a Markdown quote at the end of the text, the reply goes after it.
  React.useImperativeHandle(ref, () => ({
    quote: (q: string, from: string | null) => {
      const next = withQuote(text, q, from)
      setText(next)
      caretTo(next.length)
    },
  }))
  const canSend = (!!text.trim() || files.paths.length > 0) && !files.uploading
  // Nothing can be sent now (files uploading, a send in flight): a dictation then waits in the box.
  const busy = files.uploading || !a.enabled || run.isPending
  const alive = React.useRef(true)
  React.useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const submit = (heard?: string) => {
    const typed = text.trim()
    const v = heard ? [typed, heard].filter(Boolean).join('\n\n') : typed
    if ((!v && !files.paths.length) || busy) return
    const kept = files.atts
    files.dismissNotices()
    setText('')
    files.clear()
    // mutateAsync: its answer arrives even once this box is gone (another agent opened): the message never stays
    // stored as a draft while it is sent, and comes back (to this box or to the stored draft) only if it failed.
    run.mutateAsync({ path: a.path, text: v, reply_to: replyTo?.id, attachments: files.paths }).then(
      (r) => {
        if (r.started) {
          if (alive.current) onCancelReply()
          return
        }
        bringBackDraft(key, v, kept, t)
        toast.error(t('agents.run.notStarted'), reasonText(t, r.reason))
      },
      // The reply target stays with the text, so sending again still goes on with the same session.
      (e) => bringBackDraft(key, v, kept, t, e),
    )
  }
  // Dictation: put at the caret for review, or sent at once (voice setting "send automatically") when it can be.
  // The voice button hands the text over with the handler of the render where recording stopped: it goes through
  // `voice`, the handler of the last render, so what was typed or attached meanwhile is neither lost nor sent stale.
  const onVoice = (heard: string, autoSend: boolean) => {
    if (autoSend && !busy) return submit(heard)
    const next = insertAtCaret(input.current, text, heard)
    setText(next.text)
    caretTo(next.caret)
  }
  const voice = React.useRef(onVoice)
  voice.current = onVoice
  const onTranscript = React.useCallback((heard: string, autoSend: boolean) => voice.current(heard, autoSend), [])
  return (
    <div className="shrink-0 border-t bg-background px-3 py-3 md:px-8">
      <div className="relative mx-auto flex max-w-3xl flex-col rounded-xl border bg-card p-1.5 focus-within:border-primary/50" {...(a.enabled ? files.dropProps : {})}>
        {replyTo && (
          <div className="mb-1 flex items-center gap-2 rounded-lg bg-muted/60 py-1 pr-1 pl-2 text-[12px]" data-testid="agent-replying">
            <Reply className="size-3.5 shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{t('agents.conv.replyingTo')}</span>
              <span className="text-muted-foreground"> · {firstLine(replyTo.text)}</span>
            </span>
            <button type="button" onClick={onCancelReply} className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground pointer-coarse:grid pointer-coarse:size-10 pointer-coarse:place-items-center" aria-label={t('common.cancel')}>
              <X className="size-3.5" />
            </button>
          </div>
        )}
        {!a.enabled ? (
          <p className="px-2 py-1.5 text-sm text-muted-foreground">{t('agents.conv.paused')}</p>
        ) : (
          <>
          <AttachList atts={files.atts} onRemove={files.remove} />
          <div className="flex items-end gap-1">
            <AttachButton onFiles={files.add} />
            <Textarea
              ref={input}
              value={text}
              onPaste={files.onPaste}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                const k = files.keyAction(e)
                if (k === 'send') submit()
                else if (k === 'escape') {
                  if (replyTo) onCancelReply()
                  else e.currentTarget.blur()
                }
              }}
              minRows={1}
              maxRows={8}
              placeholder={replyTo ? t('agents.conv.replyPlaceholder', { name: a.display_name }) : t('agents.conv.placeholder', { name: a.display_name })}
              className="min-h-8 flex-1 resize-none border-0 bg-transparent px-1.5 py-1.5 text-[14px] shadow-none focus-visible:ring-0 dark:bg-transparent"
              data-testid="agent-run-text"
            />
            <VoiceButton onTranscript={onTranscript} />
            <Button size="icon-sm" onClick={() => submit()} disabled={!canSend} loading={run.isPending} aria-label={t('agents.run.now')} data-testid="agent-run">
              <Send />
            </Button>
          </div>
          </>
        )}
      </div>
      {a.chat && a.enabled && !replyTo && (
        <div className="mx-auto mt-1 flex max-w-3xl items-center justify-end gap-2 px-1 text-[11px] text-muted-foreground" data-testid="agent-chat-bar">
          {a.chat_session ? (
            <>
              <span>{t('agents.chat.goesOn')}</span>
              <button type="button" onClick={() => fresh.mutate({ path: a.path })} disabled={fresh.isPending} className="inline-flex items-center gap-1 rounded text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-new-chat">
                <MessageSquarePlus className="size-3" /> {t('agents.chat.new')}
              </button>
            </>
          ) : (
            <span>{t('agents.chat.next')}</span>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- The profile panel */
function PanelSection({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
      <div className="flex items-center gap-2">
        <h3 className="min-w-0 flex-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function Profile({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  // the settings sheet: closed, open, or open on a section
  const [advanced, setAdvanced] = React.useState<boolean | SectionId>(false)
  const [params, setParams] = useSearchParams()
  const want = params.get('settings')
  React.useEffect(() => {
    if (!want) return
    setAdvanced(want === 'mail' ? 'mail' : true)
    const p = new URLSearchParams(params)
    p.delete('settings')
    setParams(p, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [want])
  const [memory, setMemory] = React.useState(false)
  const lim = a.limits
  const spent = a.cost_today || 0
  const mode = a.approvals ? 'approvals' : a.permission_mode || 'topic'
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 p-4">
      <ProfileHead agent={a} />

      <BrokenBanner agent={a} />
      <SandboxBanner agent={a} />

      <PanelSection title={t('agents.panel.role')}>
        <RoleEditor agent={a} />
      </PanelSection>

      <PanelSection title={t('agents.panel.when')}>
        <p className="text-xs text-muted-foreground">{t('agents.when.manual')}</p>
        <AgentTriggers agent={a} onMailSettings={() => setAdvanced('mail')} />
        <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground" data-testid="agent-self-locked">
          <Lock className="mt-px size-3 shrink-0" /> {t('agents.edit.selfLocked')}
        </p>
      </PanelSection>

      <PanelSection title={t('agents.panel.guards')}>
        <div className="grid gap-1.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="flex-1">{lim.usd_per_day > 0 ? t('agents.panel.budget') : t('agents.panel.noBudget')}</span>
            <span className="text-muted-foreground tabular-nums">
              <Sensitive length={6}>{costLine(t, a)}</Sensitive>
            </span>
          </div>
          {lim.usd_per_day > 0 && (
            <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div className={cn('h-full rounded-full', spent >= lim.usd_per_day ? 'bg-destructive' : 'bg-primary')} style={{ width: `${Math.min(100, (spent / lim.usd_per_day) * 100)}%` }} />
            </div>
          )}
          {lim.runs_per_hour > 0 && <span className="text-muted-foreground tabular-nums">{t('agents.runsHour', { count: a.runs_last_hour || 0, max: lim.runs_per_hour })}</span>}
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <ShieldCheck className="size-3.5 shrink-0" /> {t(`agents.panel.mode.${mode}` as 'agents.panel.mode.topic')}
          </span>
          {a.triggers.some((x) => x.kind === 'feed') &&
            (a.trust_outside && !a.approvals ? (
              <span className="flex items-center gap-1.5 text-warning" data-testid="agent-outside-risk">
                <AlertTriangle className="size-3.5 shrink-0" /> {t('agents.panel.outsideTrusted')}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <ShieldCheck className="size-3.5 shrink-0" /> {t('agents.panel.outsideAsks')}
              </span>
            ))}
          <span className={cn('flex items-center gap-1.5', a.sandbox ? 'text-muted-foreground' : 'text-warning')} data-testid="agent-sandbox-line">
            <Lock className="size-3.5 shrink-0" /> {a.sandbox ? t('agents.panel.sandboxOn') : t('agents.panel.sandboxOff')}
          </span>
          <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
            <KeyRound className="size-3.5 shrink-0" />
            <span className="truncate">{a.keys.length ? t('agents.panel.keys', { keys: a.keys.join(', ') }) : t('agents.panel.noKeys')}</span>
          </span>
        </div>
      </PanelSection>

      <PanelSection
        title={t('agents.panel.memory')}
        action={
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setMemory(true)} data-testid="agent-memory-open">
            {t('agents.panel.memoryOpen')}
          </Button>
        }
      >
        <MemoryPreview agent={a} />
      </PanelSection>

      <div className="grid gap-2">
        <EditWithClaude agent={a} variant="row" />
        <Link
          to={`/agents/groups/new?project=${encodeURIComponent(a.project)}&with=${encodeURIComponent(a.path)}`}
          className="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left hover:bg-accent"
          data-testid="agent-new-group"
        >
          <UsersRound className="size-4 shrink-0 text-muted-foreground" />
          <span className="grid min-w-0 flex-1">
            <span className="text-sm">{t('groups.withAgent')}</span>
            <span className="truncate text-xs text-muted-foreground">{t('groups.withAgentDesc')}</span>
          </span>
        </Link>
        <button type="button" onClick={() => setAdvanced(true)} className="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left hover:bg-accent" data-testid="agent-advanced">
          <Settings2 className="size-4 shrink-0 text-muted-foreground" />
          <span className="grid min-w-0 flex-1">
            <span className="text-sm">{t('agents.panel.advanced')}</span>
            <span className="truncate text-xs text-muted-foreground">{t('agents.panel.advancedDesc')}</span>
          </span>
        </button>
      </div>
      <Sheet open={!!advanced} onOpenChange={setAdvanced}>
        <SheetContent side="right" className="md:w-[520px]">
          <SheetHeader>
            <SheetTitle>{t('agents.panel.advanced')}</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <AgentSettings agent={a} section={typeof advanced === 'string' ? advanced : undefined} />
          </SheetBody>
        </SheetContent>
      </Sheet>
      <Sheet open={memory} onOpenChange={setMemory}>
        <SheetContent side="right">
          <SheetHeader>
            <SheetTitle>{t('agents.panel.memory')}</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <MemoryEditor agent={a} />
          </SheetBody>
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** agent.json does not parse: the server keeps the agent off and sandboxed, and refuses saves - say so. */
function BrokenBanner({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  if (!a.broken) return null
  return (
    <div role="alert" className="grid gap-1 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs" data-testid="agent-broken">
      <span className="flex items-center gap-1.5 font-medium text-destructive">
        <AlertTriangle className="size-3.5 shrink-0" /> {t('agents.broken.title')}
      </span>
      <span>
        {t('agents.broken.desc', { file: `${a.path}/agent.json` })
          .split('`')
          .map((x, i) => (i % 2 ? <code key={i} className="rounded bg-muted px-1 font-mono text-[11px]">{x}</code> : x))}
      </span>
    </div>
  )
}

/** Sandbox on but this server cannot run it (bwrap, socat, the AppArmor profile...): its runs stop - say so. */
function SandboxBanner({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data } = useAgentSandbox(a.sandbox)
  if (!a.sandbox || !data || data.ok) return null
  return (
    <div role="alert" className="grid gap-1 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs" data-testid="agent-sandbox-missing">
      <span className="flex items-center gap-1.5 font-medium text-destructive">
        <AlertTriangle className="size-3.5 shrink-0" /> {t('agents.sandbox.missingTitle')}
      </span>
      <span>
        {t('agents.sandbox.missingDesc')
          .split('`')
          .map((x, i) => (i % 2 ? <code key={i} className="rounded bg-muted px-1 font-mono text-[11px]">{x}</code> : x))}
      </span>
      {data.missing.length > 0 && <span className="text-muted-foreground">{t('agents.sandbox.missingList', { list: data.missing.join(', ') })}</span>}
    </div>
  )
}

/** The role (first paragraph of its CLAUDE.md): read like text, edited in place. */
function RoleEditor({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const patch = usePatchAgent()
  const { data: ws } = useWorkspace()
  const [v, setV] = React.useState<string | null>(null)
  const dir = absTopicDir(ws, a.path)
  if (v === null)
    return (
      <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
        <button
          type="button"
          onClick={() => setV(a.description)}
          className="group min-w-0 rounded-lg bg-muted/50 px-3 py-2 text-left text-sm break-words whitespace-pre-line hover:bg-muted"
          data-testid="agent-role"
        >
          {a.description ? <Sensitive block>{a.description}</Sensitive> : <span className="text-muted-foreground italic">{t('agents.noRole')}</span>}
          <Pencil className="ml-1 inline size-3 text-muted-foreground opacity-0 group-hover:opacity-100" />
        </button>
        <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="min-w-0 flex-1 break-words">{t('agents.panel.roleHint')}</span>
          {dir && (
            <Link to={filesUrl(`${dir}/CLAUDE.md`)} className="shrink-0 hover:text-foreground hover:underline pointer-coarse:-my-3 pointer-coarse:py-3">
              CLAUDE.md
            </Link>
          )}
        </span>
      </div>
    )
  return (
    <div className="grid gap-2">
      <Textarea autoFocus minRows={4} maxRows={20} value={v} onChange={(e) => setV(e.target.value)} placeholder={t('agents.create.rolePlaceholder')} data-testid="agent-role-edit" />
      <div className="flex gap-2">
        <Button size="sm" loading={patch.isPending} onClick={() => patch.mutate({ path: a.path, description: v }, { onSuccess: () => (setV(null), toast.success(t('agents.role.saved'))) })} data-testid="agent-role-save">
          {t('common.save')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setV(null)}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}

function useMemoryFile(a: AgentDetail) {
  const { data: ws } = useWorkspace()
  const dir = absTopicDir(ws, a.path)
  const file = dir ? `${dir}/memory.md` : null
  return { file, ...useFileContent(file) }
}

/** The first lines of what it learned (memory.md without its heading). */
function MemoryPreview({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data, isLoading } = useMemoryFile(a)
  if (isLoading) return <Skeleton className="h-12 rounded-lg" />
  const lines = (data?.content || '')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#'))
  if (!lines.length) return <p className="text-xs text-muted-foreground">{t('agents.panel.memoryEmpty')}</p>
  return (
    <div className="rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
      <Sensitive block>
        {lines.slice(0, 4).map((l, i) => (
          <p key={i} className="truncate">
            {l}
          </p>
        ))}
      </Sensitive>
    </div>
  )
}

function MemoryEditor({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { file, data, isLoading, error, refetch } = useMemoryFile(a)
  const write = useWriteFile()
  const [edit, setEdit] = React.useState<string | null>(null)
  if (isLoading || !file) return <Skeleton className="h-60 rounded-xl" />
  if (error) return <EmptyState compact icon={StickyNote} title={t('agents.memory.none')} description={t('agents.memory.noneDesc')} />
  const content = data?.content || ''
  return (
    <div className="grid gap-3">
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
              <Markdown className="text-sm" localImage={clickToLoad}>
                {content}
              </Markdown>
            </React.Suspense>
          </Sensitive>
        </div>
      ) : (
        <EmptyState compact icon={StickyNote} title={t('agents.memory.empty')} description={t('agents.memory.emptyDesc')} />
      )}
    </div>
  )
}
