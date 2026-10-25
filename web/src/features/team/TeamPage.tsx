// Feature page "Team" (/team, Settings -> Features -> team_page): chats between people - direct messages and groups.
// Any message (or a summary written by Claude) can be sent to a session, existing or new. Chats go straight to the
// other people's servers (Connections).
// The open chat is in the URL (?chat=<id>).
import { useSearchParams } from 'react-router'
import * as React from 'react'
import { MessageCircleMore, UserPlus, UsersRound } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { useMediaQuery } from '@/stores/media'
import { ChatList, ChatView } from './Chat'
import { ConnectDialog } from './Connect'

/** The Connections button (page header and side panel). */
export function TeamMenu({ compact }: { compact?: boolean }) {
  const t = useT()
  const [cx, setCx] = React.useState(false)
  return (
    <>
      <ConnectDialog open={cx} onOpenChange={setCx} />
      <Button size="sm" variant={compact ? 'ghost' : 'outline'} onClick={() => setCx(true)} aria-label={t('team.cx.title')} className={compact ? 'px-2' : undefined}>
        <UserPlus /> {!compact && t('team.cx.title')}
      </Button>
    </>
  )
}

export function TeamEmpty({ compact }: { compact?: boolean }) {
  const t = useT()
  const [cx, setCx] = React.useState(false)
  return (
    <>
      <EmptyState
        icon={UsersRound}
        compact={compact}
        title={t('team.empty')}
        description={t('team.emptyDesc')}
        action={
          <Button onClick={() => setCx(true)}>
            <UserPlus /> {t('team.cx.open')}
          </Button>
        }
      />
      <ConnectDialog open={cx} onOpenChange={setCx} />
    </>
  )
}

export default function TeamPage() {
  const t = useT()
  const { data: team } = useTeam()
  const [params, setParams] = useSearchParams()
  const wide = useMediaQuery('(min-width: 768px)')
  const chatId = params.get('chat') || (wide ? team?.chats[0]?.id : null) || null
  const open = (id: string | null) => setParams(id ? { chat: id } : {}, { replace: true })
  const unread = team?.chats.reduce((n, c) => n + c.unread, 0) || 0
  // nothing yet: no chat and no contact (with contacts, the list and its + start a chat)
  const empty = team && !team.chats.length && !Object.values(team.people).some((p) => p.contact)
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title={t('team.title')} description={unread ? t('team.unread', { count: unread }) : t('team.desc')} actions={<TeamMenu />} />
      {empty ? (
        <TeamEmpty />
      ) : (
        <div className="flex min-h-0 flex-1">
          {(wide || !chatId) && (
            <aside className="flex w-full shrink-0 flex-col border-r md:w-80">
              <ChatList team={team} active={chatId} onOpen={open} />
            </aside>
          )}
          {chatId ? (
            <ChatView key={chatId} team={team} chatId={chatId} onBack={wide ? undefined : () => open(null)} />
          ) : (
            wide && (
              <div className="flex flex-1 items-center justify-center">
                <EmptyState icon={MessageCircleMore} title={t('team.pick')} />
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
