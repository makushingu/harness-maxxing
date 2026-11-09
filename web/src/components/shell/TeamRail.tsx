// Second column of the unfolded desktop sidebar while the pointer rests on "Team": the Team page's own chat list
// (features/team/Chat.tsx ChatList: unread badges, last message line). A click opens the chat in a bubble window
// (TeamBubbles.tsx, or /team?chat=<id> when Team bubbles are not shown) and folds the bar; resting on a chat shows a card with its last messages beside the column (PreviewShell, the frame of
// the session card). Lazy-loaded with the "team" texts (Sidebar.tsx). Reading the messages never marks them read.
import * as React from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useTeam, useTeamChat, type TeamChat, type TeamState } from '@/lib/queries'
import { useLang, useT } from '@/i18n'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Sensitive, Skeleton } from '@/components/ui'
import { PreviewShell } from './SessionPreview'
import { ChatList } from '@/features/team/Chat'
import { ChatAvatar, chatTitle, personOf } from '@/features/team/people'
import { useTeamUI } from '@/features/team/store'
import { useUI } from '@/stores/ui'

const PREVIEW_DELAY_MS = 250
const PREVIEW_SWITCH_MS = 70
const PREVIEW_CLOSE_MS = 140
const canHover = () => typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches
const rowOf = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLElement>('[data-chat-row]') : null)

export default function TeamRail({ onPick, shown = true }: { onPick?: () => void; shown?: boolean }) {
  const navigate = useNavigate()
  const { data: team } = useTeam()
  const setTab = useTeamUI((s) => s.setTab)
  const openChat = useTeamUI((s) => s.openChat)
  const { pathname } = useLocation()
  const bubbles = useUI((s) => s.teamBubbles)
  const box = React.useRef<HTMLDivElement>(null)
  const [at, setAt] = React.useState<{ id: string; el: HTMLElement } | null>(null)
  const openTimer = React.useRef<number | undefined>(undefined)
  const closeTimer = React.useRef<number | undefined>(undefined)
  const stop = () => {
    window.clearTimeout(openTimer.current)
    window.clearTimeout(closeTimer.current)
  }
  React.useEffect(() => stop, [])
  React.useEffect(() => {
    if (!shown) {
      stop()
      setAt(null)
    }
  }, [shown])
  const show = (el: HTMLElement, delay: number) => {
    stop()
    const next = { id: el.dataset.chatRow!, el }
    if (!delay) setAt(next)
    else openTimer.current = window.setTimeout(() => setAt(next), at ? PREVIEW_SWITCH_MS : delay)
  }
  const hide = (delay = PREVIEW_CLOSE_MS) => {
    stop()
    if (delay) closeTimer.current = window.setTimeout(() => setAt(null), delay)
    else setAt(null)
  }
  const inBox = (t: EventTarget | null) => t instanceof Node && !!box.current?.contains(t)
  const chat = at ? team?.chats.find((c) => c.id === at.id) : undefined
  return (
    <div
      ref={box}
      className="flex h-full min-h-0 flex-col"
      data-testid="team-rail"
      onPointerOver={(e) => {
        if (e.pointerType !== 'mouse' || !inBox(e.target)) return
        const row = rowOf(e.target)
        if (row && canHover()) {
          if (at?.el !== row) show(row, PREVIEW_DELAY_MS)
          else stop()
        } else if (at) hide()
      }}
      onPointerLeave={(e) => e.pointerType !== 'touch' && hide()}
      onFocus={(e) => {
        const row = inBox(e.target) ? rowOf(e.target) : null
        if (row && row.matches(':focus-visible')) show(row, 0)
      }}
      onBlur={(e) => rowOf(e.target) && hide(0)}
      onClickCapture={() => at && hide(0)}
      onScrollCapture={() => at && hide(0)}
    >
      <ChatList
        team={team}
        active={null}
        compact
        onOpen={(id) => {
          onPick?.()
          setTab('chats')
          if (!bubbles || pathname.startsWith('/team')) navigate(`/team?chat=${encodeURIComponent(id)}`)
          else openChat(id)
        }}
        onFriends={() => {
          onPick?.()
          setTab('friends')
          navigate('/team')
        }}
      />
      {shown && chat && at && box.current && (
        <ChatPreviewCard team={team} chat={chat} anchor={at.el} rail={box.current} onPointerEnter={stop} onPointerLeave={() => hide()} />
      )}
    </div>
  )
}

function ChatPreviewCard({
  team,
  chat,
  anchor,
  rail,
  onPointerEnter,
  onPointerLeave,
}: {
  team: TeamState | undefined
  chat: TeamChat
  anchor: HTMLElement
  rail: HTMLElement
  onPointerEnter: () => void
  onPointerLeave: () => void
}) {
  const t = useT()
  const lang = useLang()
  const { data, isPending } = useTeamChat(chat.id)
  const msgs = (data?.messages || []).filter((m) => m.kind !== 'info' && !m.deleted).slice(-5)
  return (
    <PreviewShell anchor={anchor} rail={rail} width={340} maxHeight={420} swapKey={chat.id} testId="team-preview" onPointerEnter={onPointerEnter} onPointerLeave={onPointerLeave}>
      <div className="flex items-center gap-2.5 border-b px-3 py-2.5">
        <ChatAvatar team={team} chat={chat} size="md" />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">
          <Sensitive length={8}>{chatTitle(team, chat)}</Sensitive>
        </span>
        {chat.last && <span className="shrink-0 text-[11px] text-muted-foreground">{fmtRelative(chat.last.at, lang)}</span>}
      </div>
      <div className="grid min-h-0 gap-2 overflow-hidden px-3 py-2.5">
        {isPending ? (
          [0, 1, 2].map((i) => <Skeleton key={i} className="h-8 rounded-lg" />)
        ) : !msgs.length ? (
          <p className="text-xs text-muted-foreground">{t('team.noMessage')}</p>
        ) : (
          msgs.map((m) => {
            const mine = m.author === team?.me
            return (
              <div key={m.id} className={cn('grid max-w-[85%] gap-0.5', mine && 'justify-self-end text-right')}>
                {!mine && chat.kind === 'group' && <span className="text-[11px] font-medium text-muted-foreground">{personOf(team, m.author).name}</span>}
                <span className={cn('line-clamp-3 rounded-lg px-2.5 py-1.5 text-left text-[13px] whitespace-pre-wrap', mine ? 'bg-primary/12' : 'bg-muted')}>
                  {m.kind === 'poll' ? `📊 ${m.poll?.question || m.text}` : m.kind === 'summary' ? `✨ ${t('team.summaryShort')}` : `${m.files?.length ? '📎 ' : ''}${m.text}`}
                </span>
              </div>
            )
          })
        )}
      </div>
    </PreviewShell>
  )
}
