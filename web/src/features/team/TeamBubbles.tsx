// Team on every page (desktop, Settings -> Features -> team_page), in floating bubbles: the Team bubble at the bottom
// right opens the chat list; a chat opens in a small card beside it (up to MAX_WINDOWS side by side); a minimized chat
// becomes a bubble with its avatar above the Team bubble, with its unread count, and a new message brings its chat's
// bubble up (Live.tsx). Which chats are open or minimized is kept per browser (store.ts).
import * as React from 'react'
import { useLocation, useNavigate } from 'react-router'
import { Maximize2, MessageCircle, Minus, X } from 'lucide-react'
import { useTeam, type TeamChat, type TeamState } from '@/lib/queries'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { Button, CountBadge, Spinner, Tooltip, toast } from '@/components/ui'
import { ChatAvatar, chatTitle } from './people'
import { useTeamUI } from './store'

// The cards' code (thread, composer, list) loads the first time one opens: the bubbles alone stay light.
const ChatView = React.lazy(() => import('./Chat').then((m) => ({ default: m.ChatView })))
const TeamSide = React.lazy(() => import('./Side').then((m) => ({ default: m.TeamSide })))

const CARD = 'flex h-[min(500px,calc(100dvh-2rem))] min-h-0 flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-pop animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200'
/** Room taken on the right by the column of bubbles (toasts and cards stay left of it). */
const COLUMN_W = 76
const CARD_W = 352
const LIST_W = 340
const GAP = 12
/** Sidebar and a margin on the left, never covered by the cards. */
const LEFT_ROOM = 96
const BUBBLE = 'relative flex size-12 items-center justify-center rounded-xl border bg-popover shadow-pop transition-colors'

/** The sidebar's unread badge, pinned to the corner of a bubble. */
function Badge({ n }: { n: number }) {
  return <CountBadge count={n} className="pointer-events-none absolute -top-1.5 -right-1.5 bg-popover" />
}

/** Header buttons: minimize + open in the Team page (chat cards), the full Team page (list card), close. */
function Tools({ onMin, chatId, onClose }: { onMin?: () => void; chatId?: string; onClose: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  return (
    <div className="flex shrink-0 items-center">
      {onMin && (
        <Tooltip content={t('team.minimize')}>
          <Button size="icon-sm" variant="ghost" onClick={onMin} aria-label={t('team.minimize')}>
            <Minus />
          </Button>
        </Tooltip>
      )}
      <Tooltip content={chatId ? t('team.openInPage') : t('team.fullPage')}>
        <Button
          size="icon-sm"
          variant="ghost"
          data-testid="bubble-expand"
          onClick={() => {
            // the chat leaves its bubble for the Team page (bubbles are not shown there)
            if (chatId) {
              useTeamUI.getState().close(chatId)
              navigate(`/team?chat=${encodeURIComponent(chatId)}`)
            } else {
              useTeamUI.getState().setList(false)
              navigate('/team')
            }
          }}
          aria-label={chatId ? t('team.openInPage') : t('team.fullPage')}
        >
          <Maximize2 className="size-3.5" />
        </Button>
      </Tooltip>
      <Tooltip content={t('common.close')}>
        <Button size="icon-sm" variant="ghost" onClick={onClose} aria-label={t('common.close')}>
          <X />
        </Button>
      </Tooltip>
    </div>
  )
}

const Loading = () => <div className="flex flex-1 items-center justify-center"><Spinner /></div>

function ChatCard({ team, id }: { team: TeamState | undefined; id: string }) {
  const minimize = useTeamUI((s) => s.minimize)
  const close = useTeamUI((s) => s.close)
  return (
    <section className={CARD} style={{ width: CARD_W }} data-team-window={id}>
      <React.Suspense fallback={<Loading />}>
        <ChatView team={team} chatId={id} compact headerExtra={<Tools onMin={() => minimize(id)} chatId={id} onClose={() => close(id)} />} />
      </React.Suspense>
    </section>
  )
}

function ListCard({ team }: { team: TeamState | undefined }) {
  const t = useT()
  const setList = useTeamUI((s) => s.setList)
  const openChat = useTeamUI((s) => s.openChat)
  return (
    <section className={CARD} style={{ width: LIST_W }} data-team-window="list">
      <div className="flex min-h-[var(--header-h)] items-center gap-2 border-b py-1.5 pr-1.5 pl-3.5">
        <span className="flex-1 text-[14.5px] font-semibold">{t('team.title')}</span>
        <Tools onClose={() => setList(false)} />
      </div>
      <React.Suspense fallback={<Loading />}>
        <TeamSide team={team} active={null} onOpen={openChat} compact />
      </React.Suspense>
    </section>
  )
}

/** the small × at the top left of a bubble, shown on hover */
const CLOSE_DOT =
  'absolute -top-1.5 -left-1.5 inline-flex size-5 items-center justify-center rounded-full border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity group-hover/head:opacity-100 hover:text-foreground focus-visible:opacity-100'

function Head({ team, chat }: { team: TeamState | undefined; chat: TeamChat }) {
  const t = useT()
  const openChat = useTeamUI((s) => s.openChat)
  const close = useTeamUI((s) => s.close)
  const title = chatTitle(team, chat)
  return (
    <div className="group/head relative animate-in fade-in-0 zoom-in-75 duration-200" data-team-head={chat.id}>
      <Tooltip content={title} side="left">
        <button type="button" onClick={() => openChat(chat.id)} aria-label={title} className={cn(BUBBLE, 'hover:border-primary/40 hover:bg-accent')}>
          <ChatAvatar team={team} chat={chat} size="md" />
          <Badge n={chat.muted ? 0 : chat.unread} />
        </button>
      </Tooltip>
      <button
        type="button"
        onClick={() => close(chat.id)}
        aria-label={t('team.closeChat')}
        title={t('team.closeChat')}
        className={CLOSE_DOT}
      >
        <X className="size-3" />
      </button>
    </div>
  )
}

function useViewportWidth() {
  return React.useSyncExternalStore(
    (on) => (window.addEventListener('resize', on), () => window.removeEventListener('resize', on)),
    () => window.innerWidth,
  )
}

export function TeamBubbles() {
  const t = useT()
  const { data: team } = useTeam()
  const list = useTeamUI((s) => s.list)
  const setList = useTeamUI((s) => s.setList)
  const setHidden = useTeamUI((s) => s.setHidden)
  const docked = useTeamUI((s) => s.docked)
  const heads = useTeamUI((s) => s.heads)
  const vw = useViewportWidth()
  // On Sessions, the bubbles sit above the message box of the session on the right.
  const lifted = useLocation().pathname.startsWith('/sessions')
  const byId = React.useMemo(() => new Map((team?.chats || []).map((c) => [c.id, c])), [team?.chats])
  // Chats that are gone (deleted, group left) leave the bubbles once the list is known.
  React.useEffect(() => {
    if (team) useTeamUI.getState().prune(new Set(team.chats.map((c) => c.id)))
  }, [team])
  // Toasts move left of the column of bubbles (components/ui/toast.tsx).
  React.useEffect(() => {
    document.documentElement.style.setProperty('--mx-bubbles-w', `${COLUMN_W}px`)
    return () => {
      document.documentElement.style.removeProperty('--mx-bubbles-w')
    }
  }, [])
  // As many cards as the window holds (the newest); the others wait as bubbles.
  const room = Math.max(1, Math.floor((vw - COLUMN_W - LEFT_ROOM - (list ? LIST_W + GAP : 0) + GAP) / (CARD_W + GAP)))
  const open = docked.filter((id) => !team || byId.has(id))
  const shown = open.slice(-room)
  const waiting = [...new Set([...open.slice(0, -room).reverse(), ...heads])].filter((id) => byId.has(id) && !shown.includes(id))
  const unread = team?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0
  return (
    <>
      <div className="pointer-events-none fixed bottom-4 z-40 flex flex-row-reverse items-end gap-3 [&>*]:pointer-events-auto" style={{ right: COLUMN_W }} data-testid="team-windows">
        {list && <ListCard team={team} />}
        {[...shown].reverse().map((id) => (
          <ChatCard key={id} team={team} id={id} />
        ))}
      </div>
      <div
        className={cn('pointer-events-none fixed right-4 z-40 flex flex-col-reverse items-center gap-2.5 transition-[bottom] [&>*]:pointer-events-auto', lifted ? 'bottom-28' : 'bottom-4')}
        data-testid="team-heads"
      >
        <div className="group/head relative">
          <Tooltip content={list ? t('nav.teamPanelClose') : t('nav.teamPanel')} side="left">
            <button
              type="button"
              onClick={() => setList(!list)}
              aria-label={t('team.title')}
              aria-expanded={list}
              className={cn(BUBBLE, list ? 'border-primary/50 bg-primary/[0.08] text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}
            >
              <MessageCircle className="size-5" />
              <Badge n={unread} />
            </button>
          </Tooltip>
          <button type="button" onClick={() => {
              setHidden(true)
              toast.action(t('team.bubblesHidden'), t('team.bubblesHiddenDesc'), { label: t('team.bubblesUndo'), onClick: () => setHidden(false) })
            }}
            aria-label={t('team.hideBubbles')} title={t('team.hideBubbles')} className={CLOSE_DOT}>
            <X className="size-3" />
          </button>
        </div>
        {waiting.map((id) => (
          <Head key={id} team={team} chat={byId.get(id)!} />
        ))}
      </div>
    </>
  )
}
