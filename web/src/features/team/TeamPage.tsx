// Feature page "Team" (/team, Settings -> Features -> team_page): chats between people - direct messages and groups.
// Any message (or a summary written by Claude) can be sent to a session, existing or new. Chats go straight to the
// other people's servers (Friends).
// The open chat is in the URL (?chat=<id>), the first one when none is (not on touch). The chats are the
// second-level sidebar (PageList; touch: the left drawer, like every page with a list). An open chat's header is the
// page's header (its name, presence, Summarize, ⋯, then New chat).
import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { MessageCircleMore, MessagesSquare, PictureInPicture2, SquarePen } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState, Tooltip } from '@/components/ui'
import { PageHeader, useDocumentTitle } from '@/components/shell/Page'
import { openPageList, TouchListButton } from '@/components/shell/TouchNav'
import { PageList } from '@/components/shell/PageList'
import { useCompact } from '@/stores/media'
import { useUI } from '@/stores/ui'
import { useTeamUI } from './store'
import { ChatView, LoadError } from './Chat'
import { TeamSide } from './Side'
import { NewChatDialog } from './Dialogs'
import { AddFriendDialog } from './Friends'
import { unreadOf } from './people'

export default function TeamPage() {
  const t = useT()
  const { data: team, isError, refetch, isFetching } = useTeam()
  const [params, setParams] = useSearchParams()
  // On touch the chats come first: opening the newest one by itself would also mark it read.
  const compact = useCompact()
  const chatId = params.get('chat') || (compact ? null : team?.chats[0]?.id) || null
  // Touch: the first chat picked is a step forward (the phone's back gesture returns to the page without one).
  const open = (id: string | null) => {
    const step = compact && !!id && !params.get('chat')
    setParams(id ? { chat: id } : {}, { replace: !step })
  }
  // A chat that is not in the loaded list (left, deleted, an old link): the page keeps its header, title and menu
  const known = !chatId || !team || team.chats.some((c) => c.id === chatId)
  const unread = unreadOf(team)
  const [query, setQuery] = React.useState('')
  const [newOpen, setNewOpen] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)
  useDocumentTitle(t('team.title'))
  // in the chat's header the labels go below 1280 px: the name of the chat keeps its room (Summarize, bubble next to it)
  const newChat = (label = 'max-[429px]:sr-only') => (
    <Button size="sm" onClick={() => setNewOpen(true)} data-testid="team-new">
      <SquarePen /> <span className={label}>{t('team.new')}</span>
    </Button>
  )
  // Bubbles on (desktop): the chat open leaves the page for a bubble, and you go back where you were.
  const bubbles = useUI((u) => u.teamBubbles) && !compact
  const navigate = useNavigate()
  const toBubble = (id: string) => {
    useTeamUI.getState().openChat(id)
    return (window.history.state?.idx ?? 0) > 0 ? navigate(-1) : navigate('/')
  }
  const chatActions = (id: string) => (
    <>
      {bubbles && (
        <Tooltip content={t('team.toBubbleHint')}>
          <Button size="sm" variant="outline" onClick={() => toBubble(id)} data-testid="team-to-bubble">
            <PictureInPicture2 /> <span className="max-xl:sr-only">{t('team.toBubble')}</span>
          </Button>
        </Tooltip>
      )}
      {newChat('max-xl:sr-only')}
    </>
  )
  return (
    <div className="flex h-full min-h-0 flex-col">
      {(!chatId || !known || (isError && !team)) && <PageHeader title={t('team.title')} description={unread ? t('team.unread', { count: unread }) : t('team.desc')} actions={newChat()} />}
      {isError && !team ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <LoadError title={t('team.loadError')} busy={isFetching} onRetry={() => refetch()} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <PageList id="team" label={t('team.title')} search={{ value: query, onChange: setQuery, placeholder: t('team.search') }}>
            <TeamSide team={team} active={chatId} onOpen={open} query={query} />
          </PageList>
          {chatId ? (
            <ChatView key={chatId} team={team} chatId={chatId} leading={compact ? <TouchListButton /> : undefined} headerExtra={chatActions(chatId)} />
          ) : (
            <div className="flex min-w-0 flex-1 items-center justify-center p-6">
              <EmptyState
                icon={MessageCircleMore}
                title={team?.chats.length ? t('team.pick') : t('team.empty')}
                description={team?.chats.length ? undefined : t('team.emptyDesc')}
                action={compact && team?.chats.length ? (
                  <Button variant="outline" onClick={openPageList}>
                    <MessagesSquare /> {t('team.tab.chats')}
                  </Button>
                ) : undefined}
              />
            </div>
          )}
        </div>
      )}
      <NewChatDialog open={newOpen} onOpenChange={setNewOpen} team={team} onCreated={open} onAddFriend={() => setAddOpen(true)} />
      <AddFriendDialog open={addOpen} onOpenChange={setAddOpen} />
    </div>
  )
}
