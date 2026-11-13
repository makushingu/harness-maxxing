// One agent (/agents/<project>/<topic>/<name>): one flow, newest at the bottom, with the box to write to it under it.
// - the owner's messages (the page, Telegram) on the right, the agent's answers on the left with its avatar: as they
//   come (its steps, what it writes, Stop), then with their steps as lines of a session; in this conversation the
//   agent is its own manager (role, memory, schedules; what it changed is said in green; a safety setting waits for
//   the owner's OK, a card in the flow). Its turns go on in one session (6 h idle or "New conversation": a new one);
// - what its automations did, in the same flow (schedules, webhooks, e-mails, other agents): what started each run
//   (a dashed card), then its answer with its steps folded in one line; Reply goes on with that run, "Open the run"
//   opens it in place (RunView), never in Sessions;
// - its profile on the right (a sheet on a phone): role edited in place, "When it works" (triggers as sentences,
//   webhook address, what came in, test; one menu adds one), protection and budget, memory, settings (a sheet).
// Opening the page marks its results as read (POST /seen).
import * as React from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  AlertCircle, AlertTriangle, ArrowLeft, Bot, Brain, Check, CheckCircle2, ChevronRight, Clock, ExternalLink, Info, KeyRound, Layers, Loader2, Lock, Mail, Maximize2, MessageSquare, MessageSquarePlus, Pencil, PlayCircle, Reply, Send, Settings2, ShieldCheck, Square, SquareTerminal, StickyNote, UsersRound, X, XCircle, Zap,
  PencilLine,
} from 'lucide-react'
import { useLang, useT, type TFn } from '@/i18n'
import { errorMessage } from '@/lib/api'
import {
  agentRoute, agentRunRoute, useAgent, useAgentSandbox, useAgentSeen, useAgentTemplates, useAgentThread, fetchAgentThreadBefore, useCrons, useFileContent, useNewAgentChat, usePatchAgent, useRunAgent, useStopSession, useWorkspace, useWriteFile,
  uploadAttachment, useCompactSession, usePatchSession, useSession,
} from '@/lib/queries'
import type { AgentDetail, AgentMessage, Approval, Cron, Effort } from '@/lib/types'
import { fmtDate, fmtDuration, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCompact, useMediaQuery } from '@/stores/media'
import {
  Badge, Button, EmptyState, Sensitive, Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle, Skeleton, StatusDot, Switch, Textarea, Tooltip, toast,
} from '@/components/ui'
import { ModelPicker } from '@/pages/sessions/Widgets'
import { Page, PageHeader } from '@/components/shell/Page'
import { absTopicDir, filesUrl, fmtCost, modelLabel, relPaths, toolIcon, type PathBases } from '@/pages/sessions/util'
import { AgentMenuButton } from './AgentMenu'
import { AgentAvatarIcon } from './Avatar'
import { AgentTriggers } from './AgentTriggers'
import { AgentSettings, readsOutside, type SectionId } from './AgentSettings'
import { ProfileHead } from './Appearance'
import { AgentsOff, ContinueButton, costLine, reasonText, useAgentsOn } from './parts'
import { CutNote, WaitingNote } from './CutNote'
import { ApprovalLine, ThreadApprovalBody, useThreadApprovals } from './approvals'
import { AttachButton, AttachList, bringBackDraft, insertAtCaret, useAttachments, useDraftText, withQuote } from './attach'
import { agentDraftKey } from '@/lib/drafts'
import { VoiceButton } from '@/features/voice/VoiceButton'
import { AttachmentStrip, MessageMedia, useMessageMenu, VoiceNote } from '@/pages/sessions/Items'
import { useSlashCommands } from '@/pages/sessions/slashCommands'
import { useSlashMenu } from '@/pages/sessions/useSlashMenu'
import { AnswerContext, AnswerText } from './answer'
import { useSessionLog } from '@/pages/sessions/log'

const Markdown = React.lazy(() => import('@/components/ui/markdown').then((m) => ({ default: m.Markdown })))
/** The memory is the agent's own writing: no picture of this site loads without a click (Markdown localImage). */
const clickToLoad = () => null

/** A result longer than this is folded (the first lines and "Read all"). */
const FOLD_CHARS = 700
/** Who wrote a run: typed by the owner (the agent page, Telegram): not a script's `maxxing agents run` (trigger manual too). */
const byOwner = (m: AgentMessage) => !!m.owner || m.source === 'manual' || m.source === 'telegram'

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
            <Button variant={wide ? 'secondary' : 'outline'} size="sm" onClick={openProfile} aria-pressed={dockable ? wide : undefined} data-testid="agent-profile-open">
              <Info /> <span className="max-sm:sr-only">{t('agents.panel.open')}</span>
            </Button>
            <AgentMenuButton agent={a} />
          </>
        }
      />
      <div className="flex min-h-0 flex-1">
        {/* keyed: a reply started on one agent never goes with a message to another */}
        <AgentCenter key={a.path} agent={a} />
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

/** An agent's conversation in a panel next to the Office (AgentsOverview, ?chat=): the same flow and box as its page,
 *  with a way to its page (profile, settings) and Close. */
export function AgentChatPanel({ path, onClose }: { path: string; onClose: () => void }) {
  const t = useT()
  const { data: a, isLoading, error } = useAgent(path)
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="office-chat" data-path={path}>
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        {a && <AgentAvatarIcon avatar={a.avatar} size={28} />}
        <div className="grid min-w-0 flex-1">
          <span className="truncate text-sm font-medium">
            <Sensitive length={8}>{a?.display_name || ''}</Sensitive>
          </span>
          {a && (
            <span className="truncate text-xs text-muted-foreground">
              <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
            </span>
          )}
        </div>
        {a && (
          <Tooltip content={t('agents.office.openPage')}>
            <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.office.openPage')}>
              <Link to={agentRoute(a)} data-testid="office-chat-page">
                <Maximize2 />
              </Link>
            </Button>
          </Tooltip>
        )}
        {a && <AgentMenuButton agent={a} />}
        <Button variant="ghost" size="icon-sm" aria-label={t('common.close')} onClick={onClose} data-testid="office-chat-close">
          <X />
        </Button>
      </div>
      {isLoading ? (
        <div className="grid gap-3 p-4">
          <Skeleton className="h-16 rounded-xl" />
          <Skeleton className="ml-10 h-16 rounded-xl" />
        </div>
      ) : error || !a ? (
        <EmptyState compact tone="error" title={t('agents.notFound')} description={errorMessage(error)} />
      ) : (
        <AgentCenter agent={a} />
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
  if (tr === 'manual' && m.source === 'command line') return t('agents.from.command')
  if (tr === 'manual' && m.source === 'conversation') return t('agents.from.conversation')
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

/** What started a run, as an icon: a schedule, an e-mail, another agent, a notification / webhook, a command. */
function triggerIcon(m: Pick<AgentMessage, 'trigger' | 'source'>) {
  const tr = m.trigger || ''
  if (tr.startsWith('cron:')) return Clock
  if (tr.startsWith('agent:')) return Bot
  if (tr === 'telegram') return Send
  if (/mail/i.test(m.source || '')) return Mail
  if (tr.startsWith('feed:')) return Zap
  if (m.source === 'command line') return SquareTerminal
  if (m.source === 'conversation') return MessageSquare
  return PlayCircle
}

/** The sessions of the owner's conversations (now, the last one, every session an own message started): their
 *  answers show their steps as a session does; every other session of the agent is a run of an automation (its
 *  steps folded). A reply to a run goes on in that run: it does not make it a conversation. */
function ownSessions(a: AgentDetail, msgs: AgentMessage[]): Set<string> {
  const own = new Set<string>()
  if (a.chat_session) own.add(a.chat_session)
  if (a.last_chat_session) own.add(a.last_chat_session)
  for (const m of msgs) if (m.kind === 'run' && m.session && byOwner(m) && !m.reply_to) own.add(m.session)
  return own
}

/** One flow, newest at the bottom: the owner's messages and the agent's answers (as they come, with their steps),
 *  and what its automations did (what started each, its steps folded, its result), a day line between days. */
function AgentCenter({ agent: a }: { agent: AgentDetail }) {
  const [replyTo, setReplyTo] = React.useState<AgentMessage | null>(null)
  // Reading the page = its results are read (again when a new one comes in while it is open).
  const seen = useAgentSeen()
  const unread = a.thread_unread || 0
  const seenMutate = seen.mutate
  React.useEffect(() => {
    if (unread > 0) seenMutate({ path: a.path })
  }, [unread, a.path, seenMutate])
  const composer = React.useRef<AgentComposerApi>(null)
  const flow = React.useRef<FlowApi>(null)
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Flow ref={flow} agent={a} onReply={setReplyTo} onSuggest={(v) => composer.current?.fill(v)} />
      <Composer ref={composer} agent={a} replyTo={replyTo} onCancelReply={() => setReplyTo(null)} onSend={() => flow.current?.toBottom()} />
    </div>
  )
}

const dayOf = (at: number) => new Date(at * 1000).toDateString()

function DayLine({ at }: { at: number }) {
  const t = useT()
  const lang = useLang()
  const d = new Date(at * 1000)
  const today = new Date()
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  const label =
    d.toDateString() === today.toDateString()
      ? t('agents.flow.today')
      : d.toDateString() === yesterday.toDateString()
        ? t('agents.flow.yesterday')
        : d.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long', ...(d.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}) })
  return <Divider>{label}</Divider>
}

function Divider({ children, testid }: { children: React.ReactNode; testid?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-1 text-xs text-muted-foreground" data-testid={testid}>
      <span className="h-px w-6 bg-border" aria-hidden />
      {children}
      <span className="h-px w-6 bg-border" aria-hidden />
    </div>
  )
}

const THREAD_PAGE = 200

type FlowApi = { toBottom: () => void }

function Flow({ agent: a, onReply, onSuggest, ref }: { agent: AgentDetail; onReply: (m: AgentMessage) => void; onSuggest?: (text: string) => void; ref?: React.Ref<FlowApi> }) {
  const t = useT()
  const { data, isLoading, error } = useAgentThread(a.path, THREAD_PAGE)
  const latest = React.useMemo(() => data?.messages || [], [data])
  // Older messages, loaded when scrolled to the top (the newest page stays live).
  const [older, setOlder] = React.useState<AgentMessage[]>([])
  const [olderDone, setOlderDone] = React.useState(false)
  const [loadingOlder, setLoadingOlder] = React.useState(false)
  const msgs = React.useMemo(() => {
    if (!older.length) return latest
    const ids = new Set(latest.map((m) => m.id))
    return [...older.filter((m) => !ids.has(m.id)), ...latest]
  }, [older, latest])
  // The live page is the last THREAD_PAGE messages: new ones push its first ones out. Once older pages are shown,
  // those go to `older` (else they would vanish between the two, and the next "older" page starts before them).
  const prevLatest = React.useRef(latest)
  React.useLayoutEffect(() => {
    const prev = prevLatest.current
    prevLatest.current = latest
    if (!older.length || prev === latest || !prev.length || !latest.length) return
    const ids = new Set(latest.map((m) => m.id))
    if (!ids.has(prev[prev.length - 1].id) && !latest.some((m) => m.at <= prev[prev.length - 1].at)) {
      // more new messages than a page (a long absence): what lies between is not known, start again from the live page
      setOlder([])
      setOlderDone(false)
      return
    }
    const first = latest[0].at
    const out = prev.filter((m) => !ids.has(m.id) && m.at <= first)
    // a frozen copy never says `waiting`: the message has started by now (or will show again from the live page)
    if (out.length) setOlder((o) => [...o, ...out.filter((m) => !o.some((x) => x.id === m.id)).map(({ waiting: _, ...m }) => m)])
  }, [latest, older.length])
  const more = !olderDone && latest.length >= THREAD_PAGE
  const { data: crons } = useCrons()
  const jobs = crons?.jobs || []
  const own = React.useMemo(() => ownSessions(a, msgs), [a, msgs])
  const byId = React.useMemo(() => new Map(msgs.map((m) => [m.id, m])), [msgs])
  const asks = useThreadApprovals(a.path, msgs)
  const { data: ws } = useWorkspace()
  const bases = React.useMemo<PathBases>(() => ({ topicDir: absTopicDir(ws, a.path), wsRoot: ws?.root || null }), [ws, a.path])
  const running = a.running_sessions || []
  const box = React.useRef<HTMLDivElement>(null)
  const last = msgs[msgs.length - 1]?.id
  // Newest at the bottom: follow it when a message arrives or a turn writes (unless the user scrolled up to read).
  const stick = React.useRef(true)
  const follow = React.useCallback(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [])
  React.useLayoutEffect(follow, [last, running.length, follow])
  // A message sent from the box below is always shown, even when the user had scrolled up to read (a long answer
  // read from its start, on a phone): back to the bottom at the send, and the message is followed when it comes.
  React.useImperativeHandle(ref, () => ({
    toBottom: () => {
      stick.current = true
      follow()
    },
  }), [follow])
  // What grows after a render (answers' markdown, images, the approval card once its query answers, a live turn)
  // stays followed while at the bottom: opening an agent shows its newest message.
  const inner = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    const el = inner.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(follow)
    ro.observe(el)
    if (box.current) ro.observe(box.current)        // the view itself (window, the box below growing)
    return () => ro.disconnect()
  }, [follow])
  // Loading older messages keeps what is on screen in place (the page grows above it). The scroller has no
  // browser scroll anchoring (`overflow-anchor: none`), so this correction is the only one, applied once.
  const keep = React.useRef<number | null>(null)
  React.useLayoutEffect(() => {
    const el = box.current
    const k = keep.current
    keep.current = null
    if (el && k !== null) el.scrollTop += el.scrollHeight - k
  }, [older])
  const loadOlder = React.useCallback(() => {
    const first = msgs[0]
    if (!more || loadingOlder || !first) return
    setLoadingOlder(true)
    fetchAgentThreadBefore(a.path, first.at, THREAD_PAGE)
      .then((r) => {
        keep.current = box.current?.scrollHeight ?? null
        if (r.messages.length < THREAD_PAGE) setOlderDone(true)
        setOlder((o) => [...r.messages, ...o])
      })
      .catch(() => setOlderDone(true))
      .finally(() => setLoadingOlder(false))
  }, [a.path, msgs, more, loadingOlder])

  const rows: { key: string; session?: string; node: React.ReactNode }[] = []
  let day = ''
  let talked = false
  for (const m of msgs) {
    if (asks.merged(m)) continue
    if (dayOf(m.at) !== day) {
      day = dayOf(m.at)
      rows.push({ key: `day:${day}`, node: <DayLine at={m.at} /> })
    }
    let node: React.ReactNode
    if (m.kind === 'note' && m.status === 'new_chat') node = <Divider testid="agent-new-chat-line">{t('agents.chat.new')}</Divider>
    else if (m.kind === 'note' && m.status === 'changed_chat') node = <ChangeLine apart icon={Settings2} text={changedText(t, m.files)} />
    else if (m.kind === 'run' && byOwner(m)) {
      // a conversation that started afresh (6 h without a word, not the first one): said above the message that opened it
      if (m.chat === 'new' && talked && !String(rows[rows.length - 1]?.key).startsWith('new:'))
        rows.push({ key: `new:${m.id}`, node: <Divider>{t('agents.chat.new')}</Divider> })
      node = <OwnerMessage m={m} answers={m.reply_to ? byId.get(m.reply_to) : undefined} />
      talked = true
    } else if (m.kind === 'run') node = <TriggerCard m={m} crons={jobs} />
    else if (m.kind === 'result')
      node = <AgentTurn m={m} agent={a} chat={!!m.session && own.has(m.session)} onReply={onReply} />
    else
      node = (
        <ThreadMessage
          m={m}
          agent={a}
          crons={jobs}
          chat={!!m.session && own.has(m.session)}
          live={m.kind === 'approval' && m.approval ? asks.live.get(m.approval) : undefined}
          decided={m.kind === 'approval' && m.approval ? asks.decided.get(m.approval) : undefined}
        />
      )
    rows.push({ key: m.id, session: m.session, node })
  }
  // A turn going on now: right under the last message of its session (the owner's message, what started the run).
  for (const s of running) {
    let at = -1
    for (let i = rows.length - 1; i >= 0; i--)
      if (rows[i].session === s.id) {
        at = i
        break
      }
    const node = <LiveTurn agent={a} sid={s.id} chat={own.has(s.id)} onWrite={follow} />
    rows.splice(at < 0 ? rows.length : at + 1, 0, { key: `live:${s.id}`, node })
  }

  return (
    <div
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        if (el.scrollTop < 200) loadOlder()
      }}
      className="min-h-0 flex-1 overflow-y-auto [overflow-anchor:none]"
      aria-live="polite"
      data-testid="agent-thread"
      data-thread
    >
      <AnswerContext owner={{ agent: a.path }}>
        <StepBases.Provider value={bases}>
        <div ref={inner} className="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] content-start gap-3 px-4 py-5 md:px-8">
          {isLoading ? (
            [0, 1, 2].map((i) => <Skeleton key={i} className={cn('h-16 rounded-xl', i % 2 && 'ml-10')} />)
          ) : error ? (
            <EmptyState tone="error" compact title={t('agents.thread.error')} description={errorMessage(error)} />
          ) : (
            <>
              {more && (
                <div className="flex justify-center py-1" data-testid="agent-thread-older">
                  {loadingOlder ? (
                    <Skeleton className="h-6 w-40 rounded-full" />
                  ) : (
                    <Button variant="ghost" size="sm" onClick={loadOlder}>{t('agents.flow.older')}</Button>
                  )}
                </div>
              )}
              {rows.map((r) => <React.Fragment key={r.key}>{r.node}</React.Fragment>)}
              {/* nothing said yet (notes such as "Agent created" aside): its greeting, and ideas when it has no role */}
              {!running.length && !msgs.some((m) => m.kind !== 'note') && (
                <div className="grid justify-items-center gap-3 py-10 text-center" data-testid="agent-start-chat">
                  <AgentAvatarIcon avatar={a.avatar} size={56} />
                  <p className="text-base font-medium">
                    <Sensitive length={8}>{t(a.description ? 'agents.chat.startTitle' : 'agents.new.startTitle', { name: a.display_name })}</Sensitive>
                  </p>
                  <p className="max-w-md text-sm text-muted-foreground">{t(a.description ? 'agents.chat.startDesc' : 'agents.new.startDesc')}</p>
                  {!a.description && onSuggest && <Suggestions onPick={onSuggest} />}
                </div>
              )}
            </>
          )}
        </div>
        </StepBases.Provider>
      </AnswerContext>
    </div>
  )
}

/** A new agent (no role yet): a blank brief and ready-made jobs of the gallery as ideas; a click puts the brief
 * in the box, to change before sending (its first […] selected). */
function Suggestions({ onPick }: { onPick: (text: string) => void }) {
  const t = useT()
  const lang = useLang()
  const { data: templates } = useAgentTemplates(lang)
  const [all, setAll] = React.useState(false)
  const chip =
    'flex items-center gap-2 rounded-full border bg-card py-1 pr-3 pl-1 text-xs transition-colors hover:border-primary/40 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
  const shown = (templates || []).filter((tp) => all || tp.first)
  const more = (templates || []).length - shown.length
  return (
    <div className="mt-2 grid w-full max-w-xl gap-2 text-left" data-testid="agent-suggestions">
      <span className="text-center text-xs text-muted-foreground">{t('agents.new.ideas')}</span>
      <div className="flex flex-wrap justify-center gap-2">
        <button type="button" onClick={() => onPick(t('agents.new.blank'))} className={cn(chip, 'pl-2.5')} data-testid="agent-suggest-blank">
          <PencilLine className="size-3.5 text-muted-foreground" aria-hidden />
          {t('agents.new.blankChip')}
        </button>
        {shown.map((tp) => (
          <button
            key={tp.id}
            type="button"
            onClick={() => onPick(tp.brief || t('agents.new.blank'))}
            className={chip}
            title={tp.summary}
            data-testid={`agent-suggest-${tp.id}`}
          >
            <AgentAvatarIcon avatar={tp.avatar} size={22} />
            {tp.name}
          </button>
        ))}
        {more > 0 && (
          <button type="button" onClick={() => setAll(true)} className={cn(chip, 'pl-3 text-muted-foreground')} data-testid="agent-suggest-more">
            {t('agents.new.moreIdeas', { n: more })}
          </button>
        )}
      </div>
    </div>
  )
}

const firstLine = (s: string) => (s || '').replace(/^[#>*\s-]+/, '').split('\n')[0].slice(0, 90)

function When({ at }: { at: number }) {
  const lang = useLang()
  return (
    <time className="text-[11px] text-muted-foreground tabular-nums" dateTime={new Date(at * 1000).toISOString()} title={fmtDate(at, lang)}>
      {fmtRelative(at, lang)}
    </time>
  )
}

/** What the owner wrote (the page, Telegram): on the right, as in a session. */
function OwnerMessage({ m, answers }: { m: AgentMessage; answers?: AgentMessage }) {
  const t = useT()
  const { onContextMenu, touch, menu } = useMessageMenu({ text: m.text, copy: true })
  return (
    <div className="group/msg relative flex flex-col items-end gap-1.5 pl-8" data-kind="run" data-owner>
      {!!m.attachments?.length && <AttachmentStrip paths={m.attachments} />}
      {m.voice?.length ? (
        // a voice message sent directly: its recording, then its words once its session transcribed them
        <div className="relative max-w-full" onContextMenu={m.text ? onContextMenu : undefined} {...(m.text ? touch : {})} data-quote>
          {menu}
          <VoiceNote paths={m.voice} heard={m.text ? { text: m.text, error: null } : m.voice_error ? { text: '', error: m.voice_error } : undefined} />
        </div>
      ) : (
        <div className="relative max-w-full rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-secondary-foreground [overflow-wrap:anywhere]" onContextMenu={onContextMenu} {...touch} data-quote>
          {menu}
          <Sensitive block>{m.text || t('agents.conv.routine')}</Sensitive>
        </div>
      )}
      <CutNote m={m} />
      <div className="flex min-w-0 max-w-full items-center gap-1.5 text-[11px] text-muted-foreground">
        {answers && (
          <span className="inline-flex min-w-0 items-center gap-1 rounded bg-muted px-1" title={t('agents.conv.replyingTo')}>
            <Reply className="size-3 shrink-0" />
            <span className="truncate">
              <Sensitive>{firstLine(answers.text)}</Sensitive>
            </span>
          </span>
        )}
        {m.trigger === 'telegram' && <span className="shrink-0">{t('agents.from.telegram')}</span>}
        <WaitingNote m={m} />
        <When at={m.at} />
      </div>
    </div>
  )
}

/** What started a run of an automation (a schedule, an e-mail, a webhook, another agent) and what it was told. */
function TriggerCard({ m, crons }: { m: AgentMessage; crons: Cron[] }) {
  const t = useT()
  const Icon = triggerIcon(m)
  return (
    <div className="grid gap-1 rounded-xl border border-dashed px-3 py-2 text-sm sm:ml-10" data-kind="run">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <span className="min-w-0 font-medium text-foreground wrap-anywhere">{t('agents.thread.started', { from: triggerLabel(t, m, crons) })}</span>
        <When at={m.at} />
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

type Step = { name: string; summary: string; state: 'ok' | 'error' | 'running' }

/** The folders the paths of the steps are shown relative to: the agent's folder ("memory.md"), then the workspace. */
const StepBases = React.createContext<PathBases>({ topicDir: null, wsRoot: null })

/** One step of a turn, as a tool line of a session (its details are in the run). */
function StepRow({ s }: { s: Step }) {
  const Icon = toolIcon(s.name)
  const bases = React.useContext(StepBases)
  // the server's summary starts with the tool's name ("Bash: ls", "Read /x"): the name is already said
  const full = s.summary.startsWith(s.name) ? s.summary.slice(s.name.length).replace(/^[:\s]+/, '') : s.summary
  const shown = relPaths(full, bases)
  return (
    <div className={cn('flex h-8 min-w-0 items-center gap-2 rounded-lg border bg-card/60 px-2.5 text-[13px]', s.state === 'error' && 'border-destructive/40')} data-testid="agent-step">
      <Icon className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="shrink-0 font-medium">{s.name.replace(/^mcp__/, '')}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={shown !== full ? full : undefined}>
        <Sensitive>{shown}</Sensitive>
      </span>
      {s.state === 'running' ? (
        <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
      ) : s.state === 'error' ? (
        <AlertCircle className="size-3.5 shrink-0 text-destructive" />
      ) : (
        <Check className="size-3.5 shrink-0 text-success" />
      )}
    </div>
  )
}

/** The steps of a run of an automation, folded in one line ("7 steps · Read · Bash · Write") that opens them. */
function StepsFold({ steps, total }: { steps: Step[]; total: number }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const names = [...new Set(steps.map((s) => s.name.replace(/^mcp__/, '')))].join(' · ')
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border bg-card/60 text-[13px]" data-testid="agent-steps">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex h-8 w-full min-w-0 items-center gap-2 px-2.5 text-left hover:bg-accent/60 max-md:h-10">
        <Layers className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="shrink-0 font-medium">{total === 1 ? t('agents.flow.step') : t('agents.flow.steps', { n: total })}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">{names}</span>
        {steps.some((s) => s.state === 'error') && <AlertCircle className="size-3.5 shrink-0 text-destructive" />}
        <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
      </button>
      {open && <StepList steps={steps} total={total} className="border-t p-1.5" />}
    </div>
  )
}

function StepList({ steps, total, className }: { steps: Step[]; total: number; className?: string }) {
  const t = useT()
  return (
    <div className={cn('grid min-w-0 gap-1', className)}>
      {total > steps.length && <p className="px-1 text-[11px] text-muted-foreground">{t('agents.flow.earlier', { n: total - steps.length })}</p>}
      {steps.map((s, i) => (
        <StepRow key={i} s={s} />
      ))}
    </div>
  )
}

/** A line of what the agent changed of itself (its memory, its role, its settings). */
function ChangeLine({ icon: Icon, text, apart }: { icon: React.ComponentType<{ className?: string }>; text: string; apart?: boolean }) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2 rounded-lg border border-success/30 bg-success/8 px-2.5 py-1.5 text-[13px]', apart && 'sm:ml-10')} data-testid="agent-change">
      <Icon className="size-3.5 shrink-0 text-success" />
      <span className="min-w-0 flex-1">{text}</span>
    </div>
  )
}

function changedText(t: TFn, files?: string[]): string {
  const what = (files || []).map((f) => (f === 'CLAUDE.md' ? t('agents.flow.role') : t('agents.flow.settings')))
  return t('agents.flow.changed', { what: [...new Set(what)].join(' + ') || t('agents.flow.settings') })
}

/** It wrote to its memory during the turn (memory.md, edited or written, without an error). */
const wroteMemory = (steps: Step[]) => steps.some((s) => /^(Edit|MultiEdit|Write)$/.test(s.name) && s.state === 'ok' && /(^|[\s/])memory\.md\b/.test(s.summary))

/** "Sonnet 5.5 · 20 s · $0.15" under an answer, as in a session. */
function ResultLine({ model, ms, cost }: { model?: string; ms?: number; cost?: number }) {
  const parts = [modelLabel(model), ms ? fmtDuration(ms / 1000) : '', cost ? fmtCost(cost) : ''].filter(Boolean)
  if (!parts.length) return null
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground tabular-nums" data-testid="result-line">
      <Check className="size-3 text-success" />
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span aria-hidden>·</span>}
          <span>{p}</span>
        </React.Fragment>
      ))}
    </div>
  )
}

/** The agent's frame: its avatar, its name and a header line, then what it did and said. */
function AgentBubble({ agent: a, head, children, className, testid }: { agent: AgentDetail; head: React.ReactNode; children: React.ReactNode; className?: string; testid?: string }) {
  return (
    <div className="flex items-start gap-2" data-kind="result" data-testid={testid}>
      <AgentAvatarIcon avatar={a.avatar} size={32} />
      <div className={cn('relative grid min-w-0 max-w-[85%] flex-1 gap-2 rounded-xl rounded-tl-sm border bg-card px-3 py-2 max-sm:max-w-full', className)}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
          <span className="min-w-0 font-medium wrap-anywhere">
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          {head}
        </div>
        {children}
      </div>
    </div>
  )
}

/** An answer of the agent: a turn of the conversation (its steps shown as in a session) or the result of a run of
 *  an automation (its steps folded, Reply goes on with it). */
function AgentTurn({ m, agent: a, chat, onReply }: { m: AgentMessage; agent: AgentDetail; chat: boolean; onReply: (m: AgentMessage) => void }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const { onContextMenu, touch, menu } = useMessageMenu({ text: m.text, copy: true })
  const failed = m.ok === false
  const long = !chat && (m.text || '').length > FOLD_CHARS     // a run's report folds, an answer never does
  const steps: Step[] = (m.tools || []).map((s) => ({ name: s.name, summary: s.summary, state: s.error ? 'error' : 'ok' }))
  const total = Math.max(m.tools_total || 0, steps.length)
  return (
    <AgentBubble
      agent={a}
      className={cn(failed && 'border-destructive/40')}
      head={
        <>
          {failed ? (
            <span className="inline-flex items-center gap-1 text-destructive">
              <XCircle className="size-3" /> {t('agents.thread.failed')}
            </span>
          ) : (
            !chat && (
              <span className="inline-flex items-center gap-1 text-success">
                <CheckCircle2 className="size-3" /> {t('agents.thread.done')}
              </span>
            )
          )}
          <When at={m.at} />
          {!chat && m.cost != null && m.cost > 0 && <span className="text-muted-foreground tabular-nums">· {fmtCost(m.cost)}</span>}
        </>
      }
    >
      {steps.length > 0 && (chat ? <StepList steps={steps} total={total} /> : <StepsFold steps={steps} total={total} />)}
      {wroteMemory(steps) && <ChangeLine icon={Brain} text={t('agents.flow.memory')} />}
      <div className="grid min-w-0" onContextMenu={onContextMenu} {...touch}>
        {menu}
        {m.text ? (
          <>
            <div className={cn('relative min-w-0 text-sm', long && !open && 'max-h-64 overflow-hidden')} data-quote>
              <Sensitive block>
                <AnswerText text={m.text} />
              </Sensitive>
              {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card" aria-hidden />}
            </div>
            <Sensitive block>
              <MessageMedia text={m.text} />
            </Sensitive>
          </>
        ) : (
          <span className="text-sm text-muted-foreground italic">{t('agents.thread.noText')}</span>
        )}
        <CutNote m={m} path={a.path} />
      </div>
      {chat && <ResultLine model={m.model} ms={m.duration_ms} cost={m.cost} />}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {long && (
          <button type="button" className="text-xs text-primary hover:underline pointer-coarse:min-h-10" onClick={() => setOpen((o) => !o)}>
            {open ? t('agents.conv.readLess') : t('agents.conv.readMore')}
          </button>
        )}
        {!chat && m.session && (
          <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary pointer-coarse:min-h-10" onClick={() => onReply(m)} data-testid="agent-reply">
            <Reply className="size-3" /> {t('agents.conv.reply')}
          </button>
        )}
        {!chat && m.session && (
          <Link to={agentRunRoute(a.path, m.session)} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-open-run">
            <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
          </Link>
        )}
        {!chat && m.session && <ContinueButton agent={a} sid={m.session} variant="link" />}
      </div>
    </AgentBubble>
  )
}

/** A turn going on now: its steps as they come, what it writes, Stop - for a run as for the conversation. */
function LiveTurn({ agent: a, sid, chat, onWrite }: { agent: AgentDetail; sid: string; chat: boolean; onWrite: () => void }) {
  const t = useT()
  const log = useSessionLog(sid)
  const stop = useStopSession()
  const waiting = (a.waiting || 0) > 0
  const { steps, text } = React.useMemo(() => {
    let from = 0
    for (let i = log.items.length - 1; i >= 0; i--)
      if (log.items[i].kind === 'user') {
        from = i + 1
        break
      }
    const steps: Step[] = []
    let text = ''
    for (const it of log.items.slice(from)) {
      if (it.kind === 'tool') steps.push({ name: it.use.name, summary: it.use.summary || '', state: !it.result ? 'running' : it.result.is_error ? 'error' : 'ok' })
      else if (it.kind === 'assistant') text = it.ev.text || ''
    }
    return { steps, text }
  }, [log])
  React.useLayoutEffect(onWrite, [steps.length, text, onWrite])
  const shown = steps.slice(-12)
  return (
    <AgentBubble
      agent={a}
      testid="agent-live"
      className={cn(waiting && 'border-warning/40')}
      head={
        waiting ? (
          <span className="inline-flex items-center gap-1 text-warning">
            <ShieldCheck className="size-3" /> {t('agents.thread.approval')}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-primary">
            <StatusDot tone="running" pulse className="size-1.5" /> {t('agents.flow.working')}
          </span>
        )
      }
    >
      {shown.length > 0 && <StepList steps={shown} total={steps.length} />}
      {text && (
        <div className="min-w-0 text-sm" data-testid="agent-live-text">
          <Sensitive block>
            <AnswerText text={text} />
          </Sensitive>
        </div>
      )}
      {!shown.length && !text && <span className="text-sm text-muted-foreground">{t('agents.conv.working', { name: a.display_name })}</span>}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive disabled:opacity-50 pointer-coarse:min-h-10" onClick={() => stop.mutate(sid)} disabled={stop.isPending} data-testid="agent-stop">
          <Square className="size-3" /> {t('agents.flow.stop')}
        </button>
        {!chat && (
          <Link to={agentRunRoute(a.path, sid)} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-follow">
            <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
          </Link>
        )}
      </div>
    </AgentBubble>
  )
}

/** The other messages of the thread: a note, a run not started (and why), a request for the owner's OK. */
function ThreadMessage({
  m, agent: a, crons, chat, live, decided,
}: {
  m: AgentMessage
  agent: AgentDetail
  crons: Cron[]
  /** of the conversation: an answered request is one line, and there is no run to open */
  chat?: boolean
  /** approval: the request while it waits (Allow / Deny), then its note (what was decided) */
  live?: Approval
  decided?: AgentMessage
}) {
  const t = useT()
  if (m.kind === 'note')
    return (
      <Divider>
        <Sensitive>{m.text}</Sensitive> · <When at={m.at} />
      </Divider>
    )
  if (m.kind === 'skip')
    return (
      <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm sm:ml-10" data-kind="skip">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span>
            {t('agents.thread.skipped', { from: triggerLabel(t, m, crons) })} <span className="text-muted-foreground">{reasonText(t, m.reason) || m.text}</span>
          </span>
          <When at={m.at} />
        </div>
      </div>
    )
  // approval: the agent asks
  if (chat && !live) return <ApprovalLine m={m} decided={decided} />
  return (
    <AgentBubble
      agent={a}
      className={cn(live && 'max-w-full border-warning/40 bg-warning/5')}
      head={
        <>
          {!live && <Badge variant="secondary">{t('agents.approval.asked')}</Badge>}
          <When at={m.at} />
        </>
      }
    >
      <ThreadApprovalBody m={m} live={live} decided={decided} />
      {m.session && !chat && (
        <Link to={agentRunRoute(a.path, m.session)} className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10" data-testid="agent-open-run">
          <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
        </Link>
      )}
    </AgentBubble>
  )
}

/** What the conversation hands to the box: a quoted selection (`from`: the agent that wrote it, null = the owner). */
type AgentComposerApi = { quote: (text: string, from: string | null) => void; fill: (text: string) => void }

function Composer({ agent: a, replyTo, onCancelReply, onSend, ref }: { agent: AgentDetail; replyTo: AgentMessage | null; onCancelReply: () => void; onSend?: () => void; ref?: React.Ref<AgentComposerApi> }) {
  const t = useT()
  const run = useRunAgent()
  const fresh = useNewAgentChat()
  const patchSession = usePatchSession()
  const compact = useCompactSession()
  // Model and effort, as in a session: those of its conversation once there is one (changed for its next turns);
  // before, the pick for the next one - the agent's model unless one is picked (a change of its settings wins again).
  const { data: chat } = useSession(a.chat_session || null)
  const setting = a.chat_model || a.model || ''
  const [picked, setModel] = React.useState<string | null>(null)
  const [pickedEffort, setEffort] = React.useState<Effort | ''>('')
  React.useEffect(() => setModel(null), [setting])
  // "" = the agent's model (the runner falls back to it), shown as "Default" with that model beside it
  const model = chat ? chat.model || '' : (picked ?? '')
  const effort = chat ? chat.effort || '' : pickedEffort
  const onModel = (m: string) => (chat ? patchSession.mutate({ id: chat.id, model: m }) : setModel(m))
  const onEffort = (e: Effort | '') => (chat ? patchSession.mutate({ id: chat.id, effort: e }) : setEffort(e))
  const chatRunning = !!chat && (chat.state === 'running' || !!chat.queue)
  const commands = useSlashCommands(a.path, {
    model,
    onModel,
    effort,
    onEffort,
    onCompact: chat
      ? () => {
          if (chatRunning) toast.info(t('slash.busy'))
          else compact.mutate(chat.id, { onSuccess: () => toast.success(t('sessions.compacting')) })
        }
      : undefined,
    onNew: a.chat_session ? () => fresh.mutate({ path: a.path }) : undefined,
    newChat: true,
    defaultModel: setting || undefined,
  })
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
  const slash = useSlashMenu({ text, setText, commands: a.enabled ? commands : undefined, input })
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
    // a suggestion of the empty conversation: the box gets it, to change or send
    // its first […] (what is left to fill in) is selected, so typing replaces it
    fill: (v: string) => {
      setText(v)
      const at = v.indexOf('[…]')
      requestAnimationFrame(() => {
        input.current?.focus()
        if (at >= 0) input.current?.setSelectionRange(at, at + 3)
        else input.current?.setSelectionRange(v.length, v.length)
      })
    },
  }))
  const canSend = (!!text.trim() || files.paths.length > 0) && !files.uploading
  // the pick for a new conversation (an existing one has its own: changed through its session)
  const nextPick = () => (chat ? {} : { model: picked || undefined, effort: pickedEffort || undefined })
  // Nothing can be sent now (files uploading, a send in flight): a dictation then waits in the box.
  const [voiceUp, setVoiceUp] = React.useState(false)
  const busy = files.uploading || !a.enabled || run.isPending || voiceUp
  const alive = React.useRef(true)
  React.useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const submit = (heard?: string) => {
    if (!heard && !files.paths.length && slash.runTyped()) return
    const typed = text.trim()
    const v = heard ? [typed, heard].filter(Boolean).join('\n\n') : typed
    if ((!v && !files.paths.length) || busy) return
    const kept = files.atts
    files.dismissNotices()
    setText('')
    files.clear()
    onSend?.()
    // mutateAsync: its answer arrives even once this box is gone (another agent opened): the message never stays
    // stored as a draft while it is sent, and comes back (to this box or to the stored draft) only if it failed.
    run.mutateAsync({ path: a.path, text: v, reply_to: replyTo?.id, attachments: files.paths, ...nextPick() }).then(
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
  // Voice message sent directly (voice setting on by default), as in a session: the recording goes at once, its
  // session transcribes it and its words fill the message. Not sendable now, or refused: it comes back attached.
  const onVoiceMessage = (file: File) => {
    if (busy) return void files.add([file])
    const reply = replyTo?.id
    onSend?.()
    setVoiceUp(true)
    uploadAttachment(a.path, file)
      .then((up) => run.mutateAsync({ path: a.path, voice: up.path, reply_to: reply, ...nextPick() }))
      .then(
        (r) => {
          if (!r.started) {
            if (alive.current) files.add([file])
            toast.error(t('agents.run.notStarted'), reasonText(t, r.reason))
          } else if (alive.current && reply) onCancelReply()
        },
        (e) => {
          if (alive.current) files.add([file])
          toast.error(errorMessage(e))
        },
      )
      .finally(() => alive.current && setVoiceUp(false))
  }
  return (
    <div className="shrink-0 border-t bg-background px-3 py-3 md:px-8">
      <div className="relative mx-auto flex max-w-3xl flex-col rounded-xl border bg-card p-1.5 focus-within:border-primary/50" {...(a.enabled ? files.dropProps : {})}>
        {slash.node}
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
                if (slash.onKeyDown(e)) return
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
            <VoiceButton onTranscript={onTranscript} onVoiceMessage={onVoiceMessage} />
            <Button size="icon-sm" onClick={() => submit()} disabled={!canSend} loading={run.isPending || voiceUp} aria-label={t('agents.run.now')} data-testid="agent-run">
              <Send />
            </Button>
          </div>
          </>
        )}
      </div>
      {a.enabled && !replyTo && (
        <div className="mx-auto mt-1 flex max-w-3xl items-center gap-2 px-1" data-testid="agent-chat-bar">
          <ModelPicker chosen={model} defaultModel={setting || undefined} real={chat?.real_model} contextTokens={chat?.context_tokens} onChange={onModel} effort={effort} onEffort={onEffort} />
          {a.chat_session && (
            <Tooltip content={t('agents.chat.newHint')}>
              <Button variant="ghost" size="sm" className="ml-auto h-7 text-xs text-muted-foreground" onClick={() => fresh.mutate({ path: a.path })} loading={fresh.isPending} data-testid="agent-new-chat">
                <MessageSquarePlus /> {t('agents.chat.new')}
              </Button>
            </Tooltip>
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
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 p-4">
      <ProfileHead agent={a} />

      <BrokenBanner agent={a} />
      <SandboxBanner agent={a} />

      <PanelSection title={t('agents.panel.role')}>
        <RoleEditor agent={a} />
      </PanelSection>

      <PanelSection title={t('agents.panel.when')}>
        <AgentTriggers agent={a} onMailSettings={() => setAdvanced('mail')} />
      </PanelSection>

      {/* protection and budget: what keeps it safe, in plain words; a click opens the setting */}
      <PanelSection title={t('agents.panel.guards')}>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5 text-xs">
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
          {lim.runs_per_hour > 0 && (a.runs_last_hour || 0) >= lim.runs_per_hour && (
            <span className="text-warning tabular-nums">{t('agents.runsHour', { count: a.runs_last_hour || 0, max: lim.runs_per_hour })}</span>
          )}
          <button
            type="button"
            onClick={() => setAdvanced('protection')}
            className={cn('-mx-1 mt-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-accent', !a.sandbox && readsOutside(a) ? 'text-warning' : 'text-muted-foreground')}
            data-testid="agent-sandbox-line"
          >
            {a.sandbox ? <ShieldCheck className="size-3.5 shrink-0" /> : <Lock className="size-3.5 shrink-0 opacity-60" />}
            <span className="min-w-0 flex-1 truncate">
              {a.sandbox
                ? a.domains?.length
                  ? t('agents.panel.sandboxSites', { sites: a.domains.join(', ') })
                  : t('agents.panel.sandboxOn')
                : t(readsOutside(a) ? 'agents.panel.sandboxAdvise' : 'agents.panel.sandboxOff')}
            </span>
          </button>
          {a.approvals && (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <ShieldCheck className="size-3.5 shrink-0" /> {t('agents.panel.mode.approvals')}
            </span>
          )}
          {a.triggers.some((x) => x.kind === 'feed') && a.trust_outside && !a.approvals && (
            <span className="flex items-center gap-1.5 text-warning" data-testid="agent-outside-risk">
              <AlertTriangle className="size-3.5 shrink-0" /> {t('agents.panel.outsideTrusted')}
            </span>
          )}
          {a.keys.length > 0 && (
            <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
              <KeyRound className="size-3.5 shrink-0" />
              <span className="truncate">{t('agents.panel.keys', { keys: a.keys.join(', ') })}</span>
            </span>
          )}
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
        <button type="button" onClick={() => setAdvanced(true)} className="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left hover:bg-accent" data-testid="agent-advanced">
          <Settings2 className="size-4 shrink-0 text-muted-foreground" />
          <span className="grid min-w-0 flex-1">
            <span className="text-sm">{t('agents.panel.advanced')}</span>
            <span className="truncate text-xs text-muted-foreground">{t('agents.panel.advancedDesc')}</span>
          </span>
        </button>
        <Link
          to={`/agents/groups/new?project=${encodeURIComponent(a.project)}&with=${encodeURIComponent(a.path)}`}
          className="flex items-center gap-1.5 justify-self-start px-1 text-xs text-muted-foreground hover:text-foreground"
          data-testid="agent-new-group"
        >
          <UsersRound className="size-3.5 shrink-0" /> {t('groups.withAgent')}
        </Link>
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
