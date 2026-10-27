// Feature page "Team" (/team, Settings -> Features -> team_page): chats between people - direct messages and groups.
// Any message (or a summary written by Claude) can be sent to a session, existing or new. Chats go straight to the
// other people's servers (Friends).
// The open chat is in the URL (?chat=<id>).
import { useSearchParams } from 'react-router'
import { MessageCircleMore, RefreshCw } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { useMediaQuery } from '@/stores/media'
import { ChatView } from './Chat'
import { TeamSide } from './Side'

export default function TeamPage() {
  const t = useT()
  const { data: team, isError, refetch, isFetching } = useTeam()
  const [params, setParams] = useSearchParams()
  const wide = useMediaQuery('(min-width: 768px)')
  const chatId = params.get('chat') || (wide ? team?.chats[0]?.id : null) || null
  const open = (id: string | null) => setParams(id ? { chat: id } : {}, { replace: true })
  const unread = team?.chats.reduce((n, c) => n + (c.muted ? 0 : c.unread), 0) || 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title={t('team.title')} description={unread ? t('team.unread', { count: unread }) : t('team.desc')} />
      {isError && !team ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <EmptyState
            tone="error"
            icon={MessageCircleMore}
            title={t('team.loadError')}
            action={
              <Button variant="outline" size="sm" className="gap-1.5" disabled={isFetching} onClick={() => refetch()}>
                <RefreshCw className="size-3.5" />
                {t('common.retry')}
              </Button>
            }
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {(wide || !chatId) && (
            <aside className="flex w-full min-w-0 shrink-0 flex-col border-r md:w-80">
              <TeamSide team={team} active={chatId} onOpen={open} />
            </aside>
          )}
          {chatId ? (
            <ChatView key={chatId} team={team} chatId={chatId} onBack={wide ? undefined : () => open(null)} />
          ) : (
            wide && (
              <div className="flex min-w-0 flex-1 items-center justify-center p-6">
                <EmptyState icon={MessageCircleMore} title={team?.chats.length ? t('team.pick') : t('team.empty')} description={team?.chats.length ? undefined : t('team.emptyDesc')} />
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
