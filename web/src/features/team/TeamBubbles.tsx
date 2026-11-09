// Team on every page (desktop, Settings -> Features -> team_page), in floating bubbles: the Team bubble at the bottom
// right opens the chat list; a chat opens in a small card beside it (up to MAX_WINDOWS side by side); a minimized chat
// becomes a bubble with its avatar above the Team bubble, with its unread count, and a new message brings its chat's
// bubble up (Live.tsx). Which chats are open or minimized is kept per browser (store.ts).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Maximize2, MessageCircle, Minus, X } from 'lucide-react'
import { useTeam, type TeamChat, type TeamState } from '@/lib/queries'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { Button, CountBadge, Tooltip } from '@/components/ui'
import { ChatView } from './Chat'
import { TeamSide } from './Side'
import { ChatAvatar, chatTitle } from './people'
import { useTeamUI } from './store'

const CARD = 'flex h-[min(500px,calc(100dvh-2rem))] min-h-0 flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-pop animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200'
const BUBBLE = 'relative flex size-12 items-center justify-center rounded-xl border bg-popover shadow-pop transition-colors'

/** The sidebar's unread badge, pinned to the corner of a bubble. */
function Badge({ n }: { n: number }) {
  return <CountBadge count={n} className="pointer-events-none absolute -top-1.5 -right-1.5 bg-popover" />
}

/** Header buttons: minimize (chat cards), the full Team page (list card), close. */
function Tools({ onMin, onClose }: { onMin?: () => void; onClose: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  return (
    <div className="flex shrink-0 items-center">
      {onMin ? (
        <Tooltip content={t('team.minimize')}>
          <Button size="icon-sm" variant="ghost" onClick={onMin} aria-label={t('team.minimize')}>
            <Minus />
          </Button>
        </Tooltip>
      ) : (
        <Tooltip content={t('team.fullPage')}>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              useTeamUI.getState().setList(false)
              navigate('/team')
            }}
            aria-label={t('team.fullPage')}
          >
            <Maximize2 className="size-3.5" />
          </Button>
        </Tooltip>
      )}
      <Tooltip content={t('common.close')}>
        <Button size="icon-sm" variant="ghost" onClick={onClose} aria-label={t('common.close')}>
          <X />
        </Button>
      </Tooltip>
    </div>
  )
}

function ChatCard({ team, id }: { team: TeamState | undefined; id: string }) {
  const ui = useTeamUI()
  return (
    <section className={cn(CARD, 'w-[352px]')} data-team-window={id}>
      <ChatView team={team} chatId={id} compact headerExtra={<Tools onMin={() => ui.minimize(id)} onClose={() => ui.close(id)} />} />
    </section>
  )
}

function ListCard({ team }: { team: TeamState | undefined }) {
  const t = useT()
  const ui = useTeamUI()
  return (
    <section className={cn(CARD, 'w-[340px]')} data-team-window="list">
      <div className="flex min-h-[var(--header-h)] items-center gap-2 border-b py-1.5 pr-1.5 pl-3.5">
        <span className="flex-1 text-[14.5px] font-semibold">{t('team.title')}</span>
        <Tools onClose={() => ui.setList(false)} />
      </div>
      <TeamSide team={team} active={null} onOpen={ui.openChat} compact />
    </section>
  )
}

function Head({ team, chat }: { team: TeamState | undefined; chat: TeamChat }) {
  const t = useT()
  const ui = useTeamUI()
  const title = chatTitle(team, chat)
  return (
    <div className="group/head relative animate-in fade-in-0 zoom-in-75 duration-200" data-team-head={chat.id}>
      <Tooltip content={title} side="left">
        <button type="button" onClick={() => ui.openChat(chat.id)} aria-label={title} className={cn(BUBBLE, 'hover:border-primary/40 hover:bg-accent')}>
          <ChatAvatar team={team} chat={chat} size="md" />
          <Badge n={chat.muted ? 0 : chat.unread} />
        </button>
      </Tooltip>
      <button
        type="button"
        onClick={() => ui.close(chat.id)}
        aria-label={t('team.closeChat')}
        title={t('team.closeChat')}
        className="absolute -top-1.5 -left-1.5 inline-flex size-5 items-center justify-center rounded-full border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/head:opacity-100 hover:text-foreground focus-visible:opacity-100"
      >
        <X className="size-3" />
      </button>
    </div>
  )
}

export function TeamBubbles() {
  const t = useT()
  const { data: team } = useTeam()
  const ui = useTeamUI()
  const byId = React.useMemo(() => new Map((team?.chats || []).map((c) => [c.id, c])), [team?.chats])
  // Chats that are gone (deleted, group left) drop out once the list is known.
  const docked = team ? ui.docked.filter((id) => byId.has(id)) : ui.docked
  const heads = (team ? ui.heads.filter((id) => byId.has(id)) : []).map((id) => byId.get(id)!)
  const unread = team?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0
  return (
    <>
      <div className="pointer-events-none fixed right-[76px] bottom-4 z-40 flex flex-row-reverse items-end gap-3 [&>*]:pointer-events-auto" data-testid="team-windows">
        {ui.list && <ListCard team={team} />}
        {[...docked].reverse().map((id) => (
          <ChatCard key={id} team={team} id={id} />
        ))}
      </div>
      <div className="pointer-events-none fixed right-4 bottom-4 z-40 flex flex-col-reverse items-center gap-2.5 [&>*]:pointer-events-auto" data-testid="team-heads">
        <Tooltip content={ui.list ? t('nav.teamPanelClose') : t('nav.teamPanel')} side="left">
          <button
            type="button"
            onClick={() => ui.setList(!ui.list)}
            aria-label={t('team.title')}
            aria-expanded={ui.list}
            className={cn(BUBBLE, ui.list ? 'border-primary/50 bg-primary/[0.08] text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}
          >
            <MessageCircle className="size-5" />
            <Badge n={unread} />
          </button>
        </Tooltip>
        {heads.map((c) => (
          <Head key={c.id} team={team} chat={c} />
        ))}
      </div>
    </>
  )
}
