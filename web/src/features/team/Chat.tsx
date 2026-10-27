// Team chats: the list, one chat (thread + composer), shared by the Team page and the side panel.
import * as React from 'react'
import { Link } from 'react-router'
import {
  ArrowLeft, BarChart3, Bell, BellOff, Check, CheckCheck, Clock, Copy, FileText, Loader2, LogOut, MessageCircleMore, MessageSquareShare, MoreHorizontal, Paperclip, Pencil, RefreshCw, Reply, Search,
  Send, Settings2, Smile, Sparkles, SquarePen, Trash2, UserPlus, Users, X,
} from 'lucide-react'
import {
  fileRawUrl, useTeamChat, useTeamConnections, useTeamDelete, useTeamEdit, useTeamLeave, useTeamMute, useTeamRead, useTeamReact, useTeamSend, useTeamSummarize,
  useTeamTyping, useTeamUpload, useTeamVote,
  type TeamChat, type TeamFile, type TeamMessage, type TeamState,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import { fmtDate } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import {
  Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, EmptyState, Input, Popover, PopoverContent, PopoverTrigger, Skeleton, Spinner,
  Textarea, Tooltip, toast,
} from '@/components/ui'
import { openFileViewer } from '@/features/files/viewerStore'
import { fmtBytes } from '@/lib/format'
import { Markdown } from '@/components/ui/markdown'
import { Avatar } from '@/features/profile/Avatar'
import { projectColor } from '@/features/tasks/model'
import { ForwardDialog, GroupDialog, NewChatDialog, PollDialog } from './Dialogs'
import { AddFriendDialog, useOpenDm } from './Friends'
import { ChatAvatar, chatTitle, friendsOf, PersonAvatar, personOf, TypingDots, usePresence, useTypingLabel } from './people'

/** fmtDate with only the given parts (its default date/time styles cannot be mixed with them). */
const fmt = (at: number, lang: string, opts: Intl.DateTimeFormatOptions) => fmtDate(at, lang, undefined, { dateStyle: undefined, timeStyle: undefined, ...opts })
function clock(at: number, lang: string) {
  return fmt(at, lang, { hour: '2-digit', minute: '2-digit' })
}
function when(at: number, lang: string) {
  const d = new Date(at * 1000)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return clock(at, lang)
  const days = (now.getTime() - d.getTime()) / 86400_000
  return fmt(at, lang, days < 6 ? { weekday: 'short' } : { day: 'numeric', month: 'short' })
}
function dayLabel(at: number, lang: string, t: ReturnType<typeof useT>) {
  const d = new Date(at * 1000)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return t('team.today')
  const y = new Date(now.getTime() - 86400_000)
  if (d.toDateString() === y.toDateString()) return t('team.yesterday')
  return fmt(at, lang, { weekday: 'long', day: 'numeric', month: 'long' })
}

/* ------------------------------------------------------------------------------------------------ list */
export function ChatList({
  team, active, onOpen, onFriends, compact,
}: {
  team: TeamState | undefined
  active: string | null
  onOpen: (id: string) => void
  onFriends: () => void
  compact?: boolean
}) {
  const t = useT()
  const lang = useLang()
  const typingLabel = useTypingLabel()
  const [q, setQ] = React.useState('')
  const [newOpen, setNewOpen] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)
  const { data: cx } = useTeamConnections()
  const dm = useOpenDm(onOpen)
  const requests = cx?.contacts.filter((x) => x.status === 'request').length || 0
  const friends = friendsOf(team)
  const chats = (team?.chats || []).filter((c) => !q || chatTitle(team, c).toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn('flex items-center gap-2', compact ? 'p-2' : 'p-3')}>
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('team.search')} className="h-8 pl-8 text-[13px]" />
        </div>
        <Tooltip content={t('team.new')}>
          <Button size="icon-sm" variant="outline" onClick={() => setNewOpen(true)} aria-label={t('team.new')}>
            <SquarePen />
          </Button>
        </Tooltip>
      </div>
      {requests > 0 && (
        <button
          type="button"
          onClick={onFriends}
          className="mx-2 mb-1 flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/[0.06] px-3 py-2 text-left text-[12.5px] font-medium hover:bg-primary/10"
        >
          <UserPlus className="size-4 text-primary" />
          {t('team.cx.pending', { count: requests })}
        </button>
      )}
      {friends.length > 0 && !q && (
        <div className="flex gap-1 overflow-x-auto px-2 pb-2 [scrollbar-width:none]" aria-label={t('team.friends.title')}>
          {friends.slice(0, 20).map(([id, p]) => (
            <button
              key={id}
              type="button"
              onClick={() => dm.open(id)}
              title={p.name}
              className="flex w-14 shrink-0 flex-col items-center gap-1 rounded-lg py-1.5 transition-colors hover:bg-accent/60"
            >
              <PersonAvatar person={p} size="lg" status />
              <span className="w-full truncate px-0.5 text-center text-[11px] text-muted-foreground">{p.name.split(' ')[0]}</span>
            </button>
          ))}
          <button type="button" onClick={() => setAddOpen(true)} title={t('team.friends.add')} className="flex w-14 shrink-0 flex-col items-center gap-1 rounded-lg py-1.5 transition-colors hover:bg-accent/60">
            <span className="inline-flex size-10 items-center justify-center rounded-full border border-dashed border-muted-foreground/40 text-muted-foreground">
              <UserPlus className="size-4" />
            </span>
            <span className="w-full truncate text-center text-[11px] text-muted-foreground">{t('team.friends.addShort')}</span>
          </button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto border-t p-1.5">
        {!team && [0, 1, 2].map((i) => <Skeleton key={i} className="m-1 h-14" />)}
        {chats.map((c) => {
          const last = c.last
          const author = last ? (last.author === team?.me ? t('team.you') : personOf(team, last.author).name.split(' ')[0]) : ''
          const writing = team?.typing?.[c.id] || []
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => onOpen(c.id)}
              className={cn(
                'flex w-full min-w-0 items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent/60',
                active === c.id && 'bg-accent',
              )}
            >
              <ChatAvatar team={team} chat={c} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className={cn('truncate text-[14px]', c.unread && !c.muted ? 'font-semibold' : 'font-medium')}>{chatTitle(team, c)}</span>
                  {c.muted && <BellOff className="size-3 shrink-0 text-muted-foreground" />}
                  {last && <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">{when(last.at, lang)}</span>}
                </span>
                <span className="flex items-center gap-2">
                  {writing.length ? (
                    <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-primary">
                      <TypingDots className="shrink-0" />
                      <span className="truncate">{c.kind === 'dm' ? t('team.typing.short') : typingLabel(team, writing)}</span>
                    </span>
                  ) : (
                    <span className={cn('truncate text-[12.5px]', c.unread && !c.muted ? 'text-foreground' : 'text-muted-foreground')}>
                      {last ? (
                        <>
                          {(c.kind === 'group' || last.author === team?.me) && <span className="text-muted-foreground">{author} : </span>}
                          {last.deleted
                            ? t('team.msg.deleted')
                            : last.kind === 'poll'
                              ? `📊 ${last.text}`
                              : last.kind === 'summary'
                                ? `✨ ${t('team.summaryShort')}`
                                : `${last.files ? '📎 ' : ''}${last.text}`}
                        </>
                      ) : (
                        t('team.noMessage')
                      )}
                    </span>
                  )}
                  {c.unread > 0 && (
                    <span
                      className={cn(
                        'ml-auto inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1 text-[10.5px] font-semibold',
                        c.muted ? 'bg-muted-foreground/25 text-foreground' : 'bg-primary text-primary-foreground',
                      )}
                    >
                      {c.unread}
                    </span>
                  )}
                </span>
              </span>
            </button>
          )
        })}
        {team && !chats.length && q && <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">{t('team.noMatch')}</p>}
        {team && !team.chats.length && !q && (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <p className="text-[13px] text-muted-foreground">{friends.length ? t('team.startHint') : t('team.friends.noneDesc')}</p>
            <Button size="sm" variant="outline" onClick={() => (friends.length ? setNewOpen(true) : setAddOpen(true))}>
              {friends.length ? <SquarePen /> : <UserPlus />} {friends.length ? t('team.new') : t('team.friends.add')}
            </Button>
          </div>
        )}
      </div>
      <NewChatDialog open={newOpen} onOpenChange={setNewOpen} team={team} onCreated={onOpen} onAddFriend={() => setAddOpen(true)} />
      <AddFriendDialog open={addOpen} onOpenChange={setAddOpen} />
    </div>
  )
}

/* ------------------------------------------------------------------------------------------------ one chat */
type Forward = { message: TeamMessage; text: string }
type Preset = 'hour' | 'two' | 'day' | 'last' | 'all'

export function ChatView({ team, chatId, onBack, compact, headerExtra }: { team: TeamState | undefined; chatId: string; onBack?: () => void; compact?: boolean; headerExtra?: React.ReactNode }) {
  const t = useT()
  const { data, isLoading, isError, isFetching, refetch } = useTeamChat(chatId)
  const failed = isError && !data
  const read = useTeamRead()
  const summarize = useTeamSummarize()
  const [forward, setForward] = React.useState<Forward | null>(null)
  const [replyTo, setReplyTo] = React.useState<TeamMessage | null>(null)
  const [editing, setEditing] = React.useState<TeamMessage | null>(null)
  const del = useTeamDelete()
  const [pollOpen, setPollOpen] = React.useState(false)
  // Summary: the messages chosen (null = not choosing)
  const [sel, setSel] = React.useState<Set<string> | null>(null)
  const [preset, setPreset] = React.useState<Preset | null>(null)
  const lastClick = React.useRef<string | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const composer = React.useRef<{ add: (files: File[]) => void }>(null)
  const scroller = React.useRef<HTMLDivElement>(null)
  const chat = data?.chat || team?.chats.find((c) => c.id === chatId)
  const msgs = React.useMemo(() => data?.messages || [], [data?.messages])
  const me = team?.me || 'me'
  const title = chat ? chatTitle(team, chat) : ''
  const pickable = React.useMemo(() => msgs.filter((m) => m.kind !== 'summary' && m.kind !== 'info' && !m.deleted), [msgs])
  const byId = React.useMemo(() => new Map(msgs.map((m) => [m.id, m])), [msgs])

  // Seen: everything shown is read (once per new message).
  const lastAt = msgs.length ? msgs[msgs.length - 1].at : 0
  const unread = chat?.unread || 0
  React.useEffect(() => {
    if (unread > 0) read.mutate(chatId)
  }, [chatId, lastAt, unread])
  // Stick to the bottom on a new message / a summary being written.
  React.useLayoutEffect(() => {
    const el = scroller.current
    if (el && !sel) el.scrollTop = el.scrollHeight
  }, [chatId, msgs.length, summarize.isPending, isLoading, (team?.typing?.[chatId] || []).length])

  const choose = (p: Preset) => {
    const now = Date.now() / 1000
    const lastSummary = [...msgs].reverse().find((m) => m.kind === 'summary')?.at || 0
    const from = p === 'hour' ? now - 3600 : p === 'two' ? now - 7200 : p === 'day' ? now - 86400 : p === 'last' ? lastSummary : 0
    setPreset(p)
    setSel(new Set(pickable.filter((m) => m.at > from).map((m) => m.id)))
  }
  const startSummary = () => {
    const lastSummary = msgs.some((m) => m.kind === 'summary')
    choose(lastSummary ? 'last' : 'all')
  }
  const toggle = (id: string, range: boolean) => {
    if (!sel) return
    const next = new Set(sel)
    const ids = pickable.map((m) => m.id)
    if (range && lastClick.current && ids.includes(lastClick.current)) {
      const [a, b] = [ids.indexOf(lastClick.current), ids.indexOf(id)].sort((x, y) => x - y)
      for (const x of ids.slice(a, b + 1)) next.add(x)
    } else if (next.has(id)) next.delete(id)
    else next.add(id)
    lastClick.current = id
    setPreset(null)
    setSel(next)
  }
  const runSummary = () => {
    if (!sel || sel.size < 2) return
    summarize.mutate(
      { cid: chatId, ids: pickable.filter((m) => sel.has(m.id)).map((m) => m.id) },
      { onSuccess: () => toast.success(t('team.summaryDone')) },
    )
    setSel(null)
  }

  const sendLabel = (m: TeamMessage) => {
    const who = m.author === me ? t('team.you') : personOf(team, m.author).name
    if (m.kind === 'summary') return t('team.fwd.fromSummary', { chat: title }) + '\n\n' + m.text + '\n\n'
    if (m.kind === 'poll' && m.poll) {
      const lines = m.poll.options.map((o) => `- ${o.label} : ${o.votes.map((v) => (v === me ? t('team.you') : personOf(team, v).name)).join(', ') || '0'}`)
      return t('team.fwd.fromPoll', { chat: title, name: who }) + `\n\n**${m.poll.question}**\n${lines.join('\n')}\n\n`
    }
    const quoted = m.text ? '\n\n' + m.text.split('\n').map((l) => `> ${l}`).join('\n') : ''
    const files = m.files?.length ? '\n\n' + t('team.fwd.files', { count: m.files.length }) : ''
    return t('team.fwd.fromMessage', { chat: title, name: who }) + quoted + files + '\n\n'
  }

  const retry = failed ? (
    <EmptyState
      compact
      tone="error"
      icon={MessageCircleMore}
      title={t('team.chatLoadError')}
      action={
        <Button variant="outline" size="sm" className="gap-1.5" disabled={isFetching} onClick={() => refetch()}>
          <RefreshCw className="size-3.5" />
          {t('common.retry')}
        </Button>
      }
    />
  ) : null
  if (!chat) return <div className="flex flex-1 items-center justify-center">{isLoading ? <Spinner /> : retry}</div>
  const writing = team?.typing?.[chatId] || []
  // "Seen" under the user's last message: who read up to it
  const lastMine = [...msgs].reverse().find((m) => m.kind !== 'info')
  const seenBy = lastMine && lastMine.author === me && !lastMine.deleted ? chat.members.filter((p) => (chat.seen?.[p] || 0) >= lastMine.at) : []
  const editLast = () => {
    const m = [...msgs].reverse().find((x) => x.author === me && x.kind === 'text' && !x.deleted)
    if (m) setEditing(m)
  }
  const remove = (m: TeamMessage) => window.confirm(t('team.msg.deleteConfirm')) && del.mutate({ cid: chatId, mid: m.id })

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const files = [...e.dataTransfer.files]
        if (files.length) composer.current?.add(files)
      }}
    >
      <header className={cn('flex min-h-[var(--header-h)] shrink-0 items-center gap-2.5 border-b', compact ? 'px-2 py-1.5' : 'px-4 py-2')}>
        {onBack && (
          <Button size="icon-sm" variant="ghost" onClick={onBack} aria-label={t('common.back')}>
            <ArrowLeft />
          </Button>
        )}
        <ChatHeader team={team} chat={chat} title={title} compact={compact} writing={writing} />
        <ChatMenu team={team} chat={chat} />
        <Tooltip content={t('team.summarizeHint')}>
          <Button size="sm" variant={sel ? 'secondary' : 'outline'} className="gap-1.5" disabled={summarize.isPending || pickable.length < 2} onClick={() => (sel ? setSel(null) : startSummary())}>
            {summarize.isPending ? <Spinner className="size-3.5" /> : <Sparkles className="size-3.5 text-primary" />}
            {!compact && t('team.summarize')}
          </Button>
        </Tooltip>
        {headerExtra}
      </header>

      <div ref={scroller} className={cn('min-h-0 flex-1 overflow-x-hidden overflow-y-auto', compact ? 'px-2.5 py-3' : 'px-4 py-4 md:px-8')}>
        <div className={cn('mx-auto flex min-w-0 flex-col', !compact && 'max-w-3xl')}>
          {isLoading && <Skeleton className="h-40" />}
          {retry}
          {msgs.map((m, i) => {
            const prev = msgs[i - 1]
            const next = msgs[i + 1]
            const newDay = !prev || new Date(prev.at * 1000).toDateString() !== new Date(m.at * 1000).toDateString()
            const card = m.kind !== 'text'
            const joinPrev = !newDay && !card && prev && prev.kind === 'text' && prev.author === m.author && m.at - prev.at < 300
            const joinNext =
              !card && next && next.kind === 'text' && next.author === m.author && next.at - m.at < 300 && new Date(next.at * 1000).toDateString() === new Date(m.at * 1000).toDateString()
            if (m.kind === 'info')
              return (
                <React.Fragment key={m.id}>
                  {newDay && <DaySeparator at={m.at} />}
                  <InfoLine team={team} m={m} />
                </React.Fragment>
              )
            return (
              <React.Fragment key={m.id}>
                {newDay && <DaySeparator at={m.at} />}
                <MessageRow
                  team={team}
                  chat={chat}
                  m={m}
                  mine={m.author === me}
                  showName={chat.kind === 'group' && !joinPrev}
                  showAvatar={!joinNext}
                  tight={!!joinPrev}
                  compact={compact}
                  selecting={!!sel && m.kind !== 'summary'}
                  selected={!!sel?.has(m.id)}
                  onSelect={(range) => toggle(m.id, range)}
                  onForward={(msg) => setForward({ message: msg, text: sendLabel(msg) })}
                  quoted={m.reply_to ? byId.get(m.reply_to) : undefined}
                  onReply={chat.left ? undefined : () => setReplyTo(m)}
                  onEdit={() => setEditing(m)}
                  onDelete={() => remove(m)}
                />
                {m === lastMine && seenBy.length > 0 && <SeenLine team={team} chat={chat} ids={seenBy} />}
              </React.Fragment>
            )
          })}
          {writing.length > 0 && !sel && <TypingRow team={team} ids={writing} />}
          {summarize.isPending && (
            <div className="mt-3 flex items-center gap-2.5 rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-3 text-[13px] text-muted-foreground">
              <Sparkles className="size-4 animate-pulse text-primary" />
              {t('team.summarizing')}
            </div>
          )}
        </div>
      </div>

      {sel ? (
        <SelectBar count={sel.size} preset={preset} compact={compact} onPreset={choose} onNone={() => (setSel(new Set()), setPreset(null))} onCancel={() => setSel(null)} onRun={runSummary} />
      ) : failed ? null : chat.left ? (
        <div className={cn('shrink-0 border-t bg-muted/30 text-center text-[13px] text-muted-foreground', compact ? 'p-3' : 'p-4')}>{t('team.group.leftNotice')}</div>
      ) : (
        <Composer
          ref={composer}
          chatId={chatId}
          title={title}
          compact={compact}
          onPoll={() => setPollOpen(true)}
          replyTo={replyTo}
          replyName={replyTo ? (replyTo.author === me ? t('team.you') : personOf(team, replyTo.author).name) : ''}
          onCancelReply={() => setReplyTo(null)}
          editing={editing}
          onCancelEdit={() => setEditing(null)}
          onEditLast={editLast}
        />
      )}
      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80 text-[14px] font-medium text-primary">
          <Paperclip className="mr-2 size-4" /> {t('team.dropFiles')}
        </div>
      )}
      <PollDialog open={pollOpen} onOpenChange={setPollOpen} chatId={chatId} />
      <ForwardDialog
        open={!!forward}
        onOpenChange={(o) => !o && setForward(null)}
        chatId={chatId}
        message={forward?.message || null}
        initialText={forward?.text || ''}
        suggestedTitle={title}
      />
    </div>
  )
}

/** Who the chat is with: the person's name and presence (never their server address), or a group's members. */
function ChatHeader({ team, chat, title, compact, writing }: { team: TeamState | undefined; chat: TeamChat; title: string; compact?: boolean; writing: string[] }) {
  const t = useT()
  const presence = usePresence()
  const typingLabel = useTypingLabel()
  const members = chat.members.map((m) => [m, personOf(team, m)] as const)
  const online = members.filter(([, p]) => p.status === 'online').length
  const sub = writing.length ? (
    <span className="flex items-center gap-1.5 text-primary">
      <TypingDots />
      {chat.kind === 'dm' ? t('team.typing.short') : typingLabel(team, writing)}
    </span>
  ) : chat.kind === 'dm' ? (
    presence(members[0][1])
  ) : (
    `${t('team.members', { count: members.length + 1 })}${online ? ` · ${t('team.online', { count: online })}` : ''}`
  )
  const face = (
    <>
      <ChatAvatar team={team} chat={chat} size={compact ? 'md' : 'lg'} />
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-[14.5px] font-semibold">{title}</span>
        <span className="block truncate text-[12px] text-muted-foreground">{sub}</span>
      </span>
    </>
  )
  if (chat.kind === 'dm') return <div className="flex min-w-0 flex-1 items-center gap-2.5">{face}</div>
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="-my-1 flex min-w-0 flex-1 items-center gap-2.5 rounded-lg py-1 pr-2 transition-colors hover:bg-accent/50">
          {face}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-1.5">
        <div className="px-2 pt-1 pb-1.5 text-[11.5px] font-semibold tracking-wide text-muted-foreground uppercase">{t('team.members', { count: members.length + 1 })}</div>
        {[...members, [team?.me || 'me', personOf(team, team?.me || 'me')] as const].map(([id, p]) => (
          <div key={id} className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
            <PersonAvatar person={p} size="md" status={id !== team?.me} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13.5px] font-medium">
                {p.name}
                {id === team?.me && <span className="font-normal text-muted-foreground"> · {t('team.you')}</span>}
                {chat.admin === id && <span className="font-normal text-muted-foreground"> · {t('team.creator')}</span>}
              </span>
              {id !== team?.me && <span className="block truncate text-[11.5px] text-muted-foreground">{presence(p)}</span>}
            </span>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  )
}

/** The chat's menu: mute; for a group, manage it (its creator) or leave it. */
function ChatMenu({ team, chat }: { team: TeamState | undefined; chat: TeamChat }) {
  const t = useT()
  const mute = useTeamMute()
  const leave = useTeamLeave()
  const [manage, setManage] = React.useState(false)
  const admin = chat.kind === 'group' && chat.admin === team?.me && !chat.left
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label={t('common.more')} className="shrink-0 text-muted-foreground">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuItem onSelect={() => mute.mutate({ cid: chat.id, muted: !chat.muted })}>
            {chat.muted ? <Bell className="size-4" /> : <BellOff className="size-4" />} {chat.muted ? t('team.mute.off') : t('team.mute.on')}
          </DropdownMenuItem>
          {admin && (
            <DropdownMenuItem onSelect={() => setManage(true)}>
              <Settings2 className="size-4" /> {t('team.group.manage')}
            </DropdownMenuItem>
          )}
          {chat.kind === 'group' && !chat.left && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={() => window.confirm(t('team.group.leaveConfirm')) && leave.mutate(chat.id)}>
                <LogOut className="size-4" /> {t('team.group.leave')}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {admin && <GroupDialog open={manage} onOpenChange={setManage} team={team} chat={chat} />}
    </>
  )
}

/** "Léa joined", "Tom left the group": a quiet line in the thread. */
function InfoLine({ team, m }: { team: TeamState | undefined; m: TeamMessage }) {
  const t = useT()
  const name = m.author === team?.me ? t('team.you') : personOf(team, m.author).name
  return <div className="my-2 text-center text-[12px] text-muted-foreground">{t(`team.info.${m.info || 'joined'}`, { name })}</div>
}

/** "Seen" (a private chat) or "Seen by Léa, Tom" (a group) under the user's last message. */
function SeenLine({ team, chat, ids }: { team: TeamState | undefined; chat: TeamChat; ids: string[] }) {
  const t = useT()
  const names = ids.map((id) => personOf(team, id).name.split(' ')[0])
  return (
    <div className="mt-1 flex items-center justify-end gap-1 px-1 text-[11px] text-muted-foreground">
      <CheckCheck className="size-3.5 text-primary" />
      {chat.kind === 'dm' ? t('team.seenMsg') : ids.length === chat.members.length ? t('team.seenAll') : t('team.seenBy', { names: names.join(', ') })}
    </div>
  )
}

/** The others writing right now: their faces and three dots, under the last message. */
function TypingRow({ team, ids }: { team: TeamState | undefined; ids: string[] }) {
  const typingLabel = useTypingLabel()
  return (
    <div className="mt-3 flex items-end gap-2 animate-in fade-in-0 slide-in-from-bottom-1" aria-live="polite">
      <span className="flex w-7 shrink-0 -space-x-2">
        {ids.slice(0, 2).map((id) => (
          <Avatar key={id} profile={personOf(team, id)} size="md" className="ring-2 ring-background" />
        ))}
      </span>
      <span className="inline-flex items-center gap-2 rounded-2xl bg-muted px-3.5 py-2.5 text-muted-foreground">
        <TypingDots />
        <span className="sr-only">{typingLabel(team, ids)}</span>
      </span>
    </div>
  )
}

function DaySeparator({ at }: { at: number }) {
  const t = useT()
  const lang = useLang()
  return (
    <div className="my-3 flex items-center gap-3 text-[11.5px] font-medium text-muted-foreground first:mt-0">
      <span className="h-px flex-1 bg-border" />
      {dayLabel(at, lang, t)}
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

/** Choosing the messages of a summary: quick ranges, then a click per message (Shift: a whole range). */
function SelectBar({
  count, preset, compact, onPreset, onNone, onCancel, onRun,
}: {
  count: number
  preset: Preset | null
  compact?: boolean
  onPreset: (p: Preset) => void
  onNone: () => void
  onCancel: () => void
  onRun: () => void
}) {
  const t = useT()
  const presets: [Preset, string][] = [
    ['hour', t('team.sum.hour')],
    ['two', t('team.sum.two')],
    ['day', t('team.sum.day')],
    ['last', t('team.sum.sinceLast')],
    ['all', t('team.sum.all')],
  ]
  return (
    <div className={cn('shrink-0 border-t bg-background', compact ? 'p-2' : 'px-4 py-3 md:px-8')}>
      <div className={cn('mx-auto flex flex-col gap-2.5 rounded-xl border border-primary/40 bg-primary/[0.04] p-2.5', !compact && 'max-w-3xl')}>
        <div className="flex flex-wrap items-center gap-1.5">
          {presets.map(([p, label]) => (
            <button
              key={p}
              type="button"
              onClick={() => onPreset(p)}
              className={cn(
                'h-7 rounded-full border px-2.5 text-[12px] font-medium transition-colors',
                preset === p ? 'border-primary bg-primary text-primary-foreground' : 'bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground',
              )}
            >
              {label}
            </button>
          ))}
          <button type="button" onClick={onNone} className="h-7 px-1.5 text-[12px] text-muted-foreground hover:text-foreground">
            {t('team.sum.none')}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex-1 text-[12.5px] text-muted-foreground">{count ? t('team.sum.count', { count }) : t('team.sum.pick')}</span>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" onClick={onRun} disabled={count < 2} className="gap-1.5">
            <Sparkles className="size-3.5" />
            {t('team.summarize')}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------------------------------------ one message */
function MessageRow({
  team, chat, m, mine, showName, showAvatar, tight, compact, selecting, selected, onSelect, onForward, quoted, onReply, onEdit, onDelete,
}: {
  team: TeamState | undefined
  chat: TeamChat
  m: TeamMessage
  mine: boolean
  showName: boolean
  showAvatar: boolean
  tight: boolean
  compact?: boolean
  selecting: boolean
  selected: boolean
  onSelect: (range: boolean) => void
  onForward: (m: TeamMessage) => void
  quoted?: TeamMessage
  onReply?: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const t = useT()
  const lang = useLang()
  const author = personOf(team, m.author)
  const quotedName = quoted ? (quoted.author === (team?.me || 'me') ? t('team.you') : personOf(team, quoted.author).name) : ''
  const card = m.kind !== 'text'
  const right = mine && !card
  return (
    <div
      id={`tm-${m.id}`}
      className={cn(
        'group/msg relative flex gap-2 rounded-xl',
        tight ? 'mt-0.5' : 'mt-3',
        selecting && 'cursor-pointer select-none -mx-2 px-2 py-0.5 transition-colors hover:bg-accent/40',
        selecting && selected && 'bg-primary/[0.07] hover:bg-primary/10',
      )}
      onClick={selecting ? (e) => onSelect(e.shiftKey) : undefined}
    >
      {selecting && (
        <span className="flex w-5 shrink-0 items-center self-center">
          <span
            className={cn(
              'inline-flex size-[18px] items-center justify-center rounded-full border transition-colors',
              selected ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40 bg-background',
            )}
          >
            {selected && <Check className="size-3" strokeWidth={3} />}
          </span>
        </span>
      )}
      <div className={cn('flex min-w-0 flex-1 gap-2', right && 'flex-row-reverse')}>
        {!right && <span className="w-7 shrink-0 self-end">{(showAvatar || card) && <Avatar profile={author} size="md" />}</span>}
        <div className={cn('flex min-w-0 flex-col', card ? 'flex-1' : 'max-w-[85%]', right && 'items-end')}>
          {(showName || card) && (
            <span className="mb-1 flex items-baseline gap-2 px-1 text-[12px]">
              <span className="font-semibold" style={{ color: mine ? undefined : projectColor(author.color || 'zinc') }}>
                {mine ? t('team.you') : author.name}
              </span>
              {card && <span className="text-muted-foreground tabular-nums">{clock(m.at, lang)}</span>}
            </span>
          )}
          <div className={cn('relative flex max-w-full min-w-0 flex-col gap-1', right && 'items-end', selecting && 'pointer-events-none')}>
            {!!m.reply_to && (
              <button
                type="button"
                onClick={() => document.getElementById(`tm-${m.reply_to}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                className={cn('flex max-w-full min-w-0 items-stretch gap-2 rounded-lg bg-muted/60 py-1 pr-2.5 pl-1 text-left text-[12px] hover:bg-muted', right && 'self-end')}
              >
                <span className="w-[3px] shrink-0 rounded-full bg-primary/60" />
                <span className="min-w-0">
                  <span className="block font-medium">{quoted ? quotedName : t('team.msg.unknown')}</span>
                  <span className="line-clamp-2 text-muted-foreground [overflow-wrap:anywhere]">
                    {!quoted ? '' : quoted.deleted ? t('team.msg.deleted') : quoted.kind === 'poll' ? `📊 ${quoted.poll?.question}` : quoted.text || `📎 ${quoted.files?.map((f) => f.name).join(', ')}`}
                  </span>
                </span>
              </button>
            )}
            {m.deleted ? (
              <div className="rounded-2xl border border-dashed px-3.5 py-2 text-[13px] text-muted-foreground italic">{t('team.msg.deleted')}</div>
            ) : (
              !!m.files?.length && <Files files={m.files} right={right} />
            )}
            {m.deleted ? null : m.kind === 'summary' ? (
              <SummaryCard m={m} />
            ) : m.kind === 'poll' ? (
              <PollCard team={team} chat={chat} m={m} />
            ) : m.text ? (
              <div
                className={cn(
                  'max-w-full rounded-2xl px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]',
                  mine ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground',
                  mine ? (tight ? 'rounded-tr-md' : '') : tight ? 'rounded-tl-md' : '',
                )}
              >
                <Linkified text={m.text} mine={mine} />
                <span className={cn('ml-2 inline-flex translate-y-0.5 items-center gap-1 text-[10.5px] tabular-nums', mine ? 'text-primary-foreground/70' : 'text-muted-foreground')}>
                  {!!m.edited && <span>{t('team.msg.edited')}</span>}
                  {clock(m.at, lang)}
                  {mine && !!m.pending?.length && (
                    <span title={t('team.notDelivered', { names: m.pending.map((p) => personOf(team, p).name).join(', ') })}>
                      <Clock className="size-3" />
                    </span>
                  )}
                </span>
              </div>
            ) : null}
            {!selecting && !m.deleted && (
              <MessageTools team={team} chat={chat} m={m} mine={right} own={mine} compact={compact} onForward={() => onForward(m)} onReply={onReply} onEdit={onEdit} onDelete={onDelete} />
            )}
          </div>
          {!!m.reactions && Object.keys(m.reactions).length > 0 && <Reactions team={team} chat={chat} m={m} />}
          {!!m.sent?.length && (
            <div className={cn('mt-1 flex flex-wrap gap-1', right && 'justify-end')}>
              {m.sent.map((s, i) => (
                <Link
                  key={i}
                  to={`/sessions/${s.session}`}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-[11px] text-muted-foreground hover:border-primary/50 hover:text-foreground"
                >
                  <MessageSquareShare className="size-3 text-primary" />
                  <span className="truncate">{t('team.sentTo', { title: s.title || s.session })}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const URL_RE = /(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]])/g

/** A message's text with its web links clickable (opened in a new tab, nothing else is interpreted). */
function Linkified({ text, mine }: { text: string; mine: boolean }) {
  const parts = text.split(URL_RE)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 ? (
          <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow" className={cn('underline underline-offset-2', mine ? 'decoration-primary-foreground/50' : 'text-primary decoration-primary/40')} onClick={(e) => e.stopPropagation()}>
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </>
  )
}

/** Files of a message: pictures as thumbnails, other files as chips; a click opens the file viewer. */
function Files({ files: all, right }: { files: (TeamFile & { pending?: boolean; failed?: boolean })[]; right: boolean }) {
  const t = useT()
  const files = all.filter((f) => f.path)
  const waiting = all.filter((f) => !f.path)
  const paths = files.map((f) => f.path)
  const images = files.filter((f) => f.mime.startsWith('image/'))
  const others = files.filter((f) => !f.mime.startsWith('image/'))
  return (
    <div className={cn('flex max-w-full min-w-0 flex-col gap-1', right && 'items-end')}>
      {!!images.length && (
        <div className={cn('flex flex-wrap gap-1', right && 'justify-end')}>
          {images.map((f) => (
            <button key={f.path} type="button" onClick={() => openFileViewer(f.path, paths)} className="max-w-full overflow-hidden rounded-xl border bg-muted transition-opacity hover:opacity-90">
              <img src={fileRawUrl(f.path)} alt={f.name} loading="lazy" className={cn('block max-w-full object-cover', images.length > 1 ? 'size-36' : 'max-h-60 w-auto sm:max-w-[300px]')} />
            </button>
          ))}
        </div>
      )}
      {waiting.map((f) => (
        <span key={f.name} className={cn('flex max-w-full items-center gap-2.5 rounded-xl border border-dashed px-3 py-2 text-[12.5px]', f.failed ? 'text-destructive' : 'text-muted-foreground')}>
          {f.failed ? <X className="size-4" /> : <Loader2 className="size-4 animate-spin" />}
          <span className="min-w-0 truncate">{f.name}</span>
          <span className="shrink-0">{f.failed ? t('team.fileFailed') : `${fmtBytes(f.size)} · ${t('team.fileLoading')}`}</span>
        </span>
      ))}
      {others.map((f) => (
        <button
          key={f.path}
          type="button"
          onClick={() => openFileViewer(f.path, paths)}
          className="flex max-w-full min-w-0 items-center gap-2.5 rounded-xl border bg-card px-3 py-2 text-left sm:max-w-[300px] transition-colors hover:border-primary/50"
        >
          <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="size-4" />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium">{f.name}</span>
            <span className="block text-[11.5px] text-muted-foreground">{fmtBytes(f.size)}</span>
          </span>
        </button>
      ))}
    </div>
  )
}

function MessageTools({
  team, chat, m, mine, own, compact, onForward, onReply, onEdit, onDelete,
}: {
  team: TeamState | undefined
  chat: TeamChat
  m: TeamMessage
  mine: boolean
  own: boolean
  compact?: boolean
  onForward: () => void
  onReply?: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const t = useT()
  const react = useTeamReact()
  const [open, setOpen] = React.useState(false)
  const [menu, setMenu] = React.useState(false)
  const tool = 'inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
  const copy = () => {
    void navigator.clipboard?.writeText(m.text).then(() => toast.success(t('team.copied')))
  }
  return (
    <div
      className={cn(
        'absolute -top-3.5 z-10 flex items-center gap-0.5 rounded-lg border bg-popover p-0.5 opacity-0 shadow-sm transition-opacity group-hover/msg:opacity-100 focus-within:opacity-100',
        (open || menu) && 'opacity-100',
        mine ? 'left-1' : 'right-1',
      )}
    >
      {onReply && !chat.left && (
        <Tooltip content={t('team.msg.reply')}>
          <button type="button" onClick={onReply} className={tool} aria-label={t('team.msg.reply')}>
            <Reply className="size-4" />
          </button>
        </Tooltip>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button type="button" className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={t('team.react')}>
            <Smile className="size-4" />
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" className="flex w-auto gap-0.5 p-1">
          {(team?.reactions || []).map((e) => (
            <button
              key={e}
              type="button"
              className="inline-flex size-8 items-center justify-center rounded-md text-lg transition-transform hover:scale-125 hover:bg-accent"
              onClick={() => {
                react.mutate({ cid: chat.id, mid: m.id, emoji: e })
                setOpen(false)
              }}
            >
              {e}
            </button>
          ))}
        </PopoverContent>
      </Popover>
      <Tooltip content={t('team.forward')}>
        <button type="button" onClick={onForward} className="inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-[12px] font-medium text-primary hover:bg-primary/10" aria-label={t('team.forward')}>
          <MessageSquareShare className="size-4" />
          {!compact && t('team.toSession')}
        </button>
      </Tooltip>
      <DropdownMenu open={menu} onOpenChange={setMenu}>
        <DropdownMenuTrigger asChild>
          <button type="button" className={tool} aria-label={t('common.more')}>
            <MoreHorizontal className="size-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align={mine ? 'start' : 'end'} className="w-48">
          {!!m.text && (
            <DropdownMenuItem onSelect={copy}>
              <Copy className="size-4" /> {t('team.copy')}
            </DropdownMenuItem>
          )}
          {own && m.kind === 'text' && !chat.left && (
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil className="size-4" /> {t('team.msg.edit')}
            </DropdownMenuItem>
          )}
          {own && !chat.left && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={onDelete}>
                <Trash2 className="size-4" /> {t('team.msg.delete')}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function Reactions({ team, chat, m }: { team: TeamState | undefined; chat: TeamChat; m: TeamMessage }) {
  const react = useTeamReact()
  const me = team?.me || 'me'
  return (
    <div className="mt-1 flex flex-wrap gap-1 px-1">
      {Object.entries(m.reactions || {}).map(([e, who]) => (
        <Tooltip key={e} content={who.map((w) => (w === me ? '✓' : personOf(team, w).name)).join(', ')}>
          <button
            type="button"
            onClick={() => react.mutate({ cid: chat.id, mid: m.id, emoji: e })}
            className={cn(
              'inline-flex h-6 items-center gap-1 rounded-full border px-1.5 text-[12px] tabular-nums transition-colors',
              who.includes(me) ? 'border-primary/50 bg-primary/10 text-foreground' : 'bg-background text-muted-foreground hover:bg-accent',
            )}
          >
            <span>{e}</span>
            {who.length}
          </button>
        </Tooltip>
      ))}
    </div>
  )
}

/** A summary may come from another server: no remote picture (it would tell its owner who reads it, and when). */
const NO_IMAGES = { img: ({ alt }: { alt?: string }) => (alt ? <span className="text-muted-foreground">[{alt}]</span> : null) }

function SummaryCard({ m }: { m: TeamMessage }) {
  const t = useT()
  const s = m.summary
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border border-primary/30 bg-gradient-to-b from-primary/[0.07] to-transparent">
      <div className="flex items-center gap-2 border-b border-primary/20 px-3.5 py-2 text-[12px] font-medium">
        <Sparkles className="size-3.5 text-primary" />
        {t('team.summaryBy')}
        {s && <span className="ml-auto font-normal text-muted-foreground">{t('team.summaryOf', { count: s.count })}</span>}
      </div>
      <Markdown components={NO_IMAGES} className="min-w-0 px-3.5 py-2.5 text-[13.5px] [overflow-wrap:anywhere] [&_p]:my-1.5 [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_ul]:my-1">{m.text}</Markdown>
    </div>
  )
}

/** A poll: round buttons for one choice, square boxes when several answers are allowed. */
function PollCard({ team, chat, m }: { team: TeamState | undefined; chat: TeamChat; m: TeamMessage }) {
  const t = useT()
  const vote = useTeamVote()
  const me = team?.me || 'me'
  const poll = m.poll!
  const voters = new Set(poll.options.flatMap((o) => o.votes)).size
  const max = Math.max(1, ...poll.options.map((o) => o.votes.length))
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-2 px-3.5 pt-3 pb-1">
        <BarChart3 className="size-4 text-primary" />
        <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{poll.multi ? t('team.poll.multi') : t('team.poll.single')}</span>
      </div>
      <div className="px-3.5 pb-2 text-[15px] font-semibold [overflow-wrap:anywhere]">{poll.question}</div>
      <div className="flex flex-col gap-1.5 px-2.5 pb-2.5">
        {poll.options.map((o) => {
          const pct = voters ? Math.round((o.votes.length / voters) * 100) : 0
          const mineVote = o.votes.includes(me)
          return (
            <button
              key={o.id}
              type="button"
              onClick={() => vote.mutate({ cid: chat.id, mid: m.id, option: o.id })}
              className={cn('relative flex items-center gap-2.5 overflow-hidden rounded-lg border px-3 py-2 text-left transition-colors hover:border-primary/50', mineVote && 'border-primary/60')}
            >
              <span
                className={cn('absolute inset-y-0 left-0 transition-[width] duration-500', mineVote ? 'bg-primary/15' : 'bg-muted', o.votes.length === max && voters > 0 && !mineVote && 'bg-muted-foreground/15')}
                style={{ width: `${pct}%` }}
              />
              <span
                className={cn(
                  'relative inline-flex size-4 shrink-0 items-center justify-center border',
                  poll.multi ? 'rounded-[4px]' : 'rounded-full',
                  mineVote ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40',
                )}
              >
                {mineVote && <Check className="size-2.5" strokeWidth={3} />}
              </span>
              <span className="relative min-w-0 flex-1 truncate text-[13.5px] font-medium">{o.label}</span>
              <span className="relative flex -space-x-1.5">
                {o.votes.slice(0, 4).map((v) => (
                  <Avatar key={v} profile={personOf(team, v)} size="sm" className="ring-2 ring-card" />
                ))}
              </span>
              <span className="relative w-9 text-right text-[12px] text-muted-foreground tabular-nums">{pct}%</span>
            </button>
          )
        })}
      </div>
      <div className="flex items-center gap-2 border-t px-3.5 py-2 text-[11.5px] text-muted-foreground">
        <Users className="size-3.5" />
        {t('team.poll.voters', { count: voters })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------------------------------------ composer */
type Pending = { key: string; name: string; file?: TeamFile; failed?: boolean }

function Composer({
  chatId, title, compact, onPoll, replyTo, replyName, onCancelReply, editing, onCancelEdit, onEditLast, ref,
}: {
  chatId: string
  title: string
  compact?: boolean
  onPoll: () => void
  replyTo: TeamMessage | null
  replyName: string
  onCancelReply: () => void
  editing: TeamMessage | null
  onCancelEdit: () => void
  onEditLast: () => void
  ref?: React.Ref<{ add: (files: File[]) => void }>
}) {
  const t = useT()
  const send = useTeamSend()
  const edit = useTeamEdit()
  const draft = React.useRef('')
  const upload = useTeamUpload()
  const typing = useTeamTyping()
  const lastTyping = React.useRef(0)
  const [text, setText] = React.useState('')
  const [pending, setPending] = React.useState<Pending[]>([])
  const input = React.useRef<HTMLTextAreaElement>(null)
  const picker = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    setText('')
    setPending([])
    input.current?.focus()
  }, [chatId])
  // editing a message: its text in the box (the draft comes back after); replying: the focus
  React.useEffect(() => {
    if (editing) {
      draft.current = text
      setText(editing.text)
    }
    input.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing?.id, replyTo?.id])
  const stopEditing = () => {
    setText(draft.current)
    onCancelEdit()
  }
  const add = React.useCallback(
    (files: File[]) => {
      const batch = files.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, name: f.name }))
      setPending((p) => [...p, ...batch])
      upload.mutate(files, {
        onSuccess: (r) => setPending((p) => p.map((x) => { const i = batch.findIndex((b) => b.key === x.key); return i >= 0 ? { ...x, file: r.files[i] } : x })),
        onError: () => setPending((p) => p.map((x) => (batch.some((b) => b.key === x.key) ? { ...x, failed: true } : x))),
      })
    },
    [upload],
  )
  React.useImperativeHandle(ref, () => ({ add }), [add])
  const uploading = pending.some((p) => !p.file && !p.failed)
  const ready = pending.filter((p) => p.file)
  const submit = () => {
    const v = text.trim()
    if (editing) {
      if (!v && !editing.files?.length) return
      edit.mutate({ cid: chatId, mid: editing.id, text: v })
      setText(draft.current)
      onCancelEdit()
      return
    }
    if ((!v && !ready.length) || uploading) return
    const files = ready.map((p) => ({ path: p.file!.path }))
    setText('')
    setPending([])
    lastTyping.current = 0
    send.mutate({ cid: chatId, text: v, files, reply_to: replyTo?.id }, { onError: () => setText(v) })
    onCancelReply()
  }
  return (
    <div className={cn('shrink-0 border-t bg-background', compact ? 'p-2' : 'px-4 py-3 md:px-8')}>
      <div className={cn('mx-auto flex flex-col rounded-xl border bg-card p-1.5 focus-within:border-primary/50', !compact && 'max-w-3xl')}>
        {(editing || replyTo) && (
          <div className="mb-1 flex items-center gap-2 rounded-lg bg-muted/60 py-1 pr-1 pl-2 text-[12px]">
            {editing ? <Pencil className="size-3.5 shrink-0 text-primary" /> : <Reply className="size-3.5 shrink-0 text-primary" />}
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{editing ? t('team.msg.editing') : t('team.msg.replyingTo', { name: replyName })}</span>
              {!editing && replyTo && <span className="text-muted-foreground"> · {replyTo.text || replyTo.poll?.question || replyTo.files?.map((f) => f.name).join(', ')}</span>}
            </span>
            <button type="button" onClick={editing ? stopEditing : onCancelReply} className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={t('common.cancel')}>
              <X className="size-3.5" />
            </button>
          </div>
        )}
        {!!pending.length && (
          <div className="flex flex-wrap gap-1.5 px-1 pt-0.5 pb-1.5">
            {pending.map((p) => (
              <span key={p.key} className={cn('inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border bg-background py-1 pr-1 pl-2 text-[12px]', p.failed && 'border-destructive/50 text-destructive')}>
                {!p.file && !p.failed ? <Loader2 className="size-3.5 animate-spin" /> : p.file?.mime.startsWith('image/') ? <img src={fileRawUrl(p.file.path)} alt="" className="size-5 rounded object-cover" /> : <FileText className="size-3.5" />}
                <span className="truncate">{p.name}</span>
                <button type="button" onClick={() => setPending((x) => x.filter((y) => y.key !== p.key))} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={t('common.delete')}>
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-1">
          <Tooltip content={t('team.attach')}>
            <Button size="icon-sm" variant="ghost" onClick={() => picker.current?.click()} aria-label={t('team.attach')} className="text-muted-foreground">
              <Paperclip />
            </Button>
          </Tooltip>
          <Tooltip content={t('team.poll.new')}>
            <Button size="icon-sm" variant="ghost" onClick={onPoll} aria-label={t('team.poll.new')} className="text-muted-foreground">
              <BarChart3 />
            </Button>
          </Tooltip>
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              const files = [...(e.target.files || [])]
              e.target.value = ''
              if (files.length) add(files)
            }}
          />
          <Textarea
            ref={input}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              const now = Date.now()
              if (!editing && e.target.value.trim() && now - lastTyping.current > 2500) {
                lastTyping.current = now
                typing.mutate(chatId)
              }
            }}
            onPaste={(e) => {
              const files = [...e.clipboardData.files]
              if (files.length) {
                e.preventDefault()
                add(files)
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              } else if (e.key === 'Escape' && (editing || replyTo)) {
                e.preventDefault()
                if (editing) stopEditing()
                else onCancelReply()
              } else if (e.key === 'ArrowUp' && !text && !editing && !pending.length) {
                e.preventDefault()
                onEditLast()
              }
            }}
            minRows={1}
            maxRows={8}
            placeholder={t('team.placeholder', { chat: title })}
            className="min-h-8 flex-1 resize-none border-0 bg-transparent px-1.5 py-1.5 text-[14px] shadow-none focus-visible:ring-0 dark:bg-transparent"
          />
          <Button size="icon-sm" onClick={submit} disabled={editing ? !text.trim() && !editing.files?.length : (!text.trim() && !ready.length) || uploading} aria-label={editing ? t('team.msg.save') : t('team.send')}>
            {editing ? <Check /> : <Send />}
          </Button>
        </div>
      </div>
    </div>
  )
}
