// Feature page "Team" (/team, Settings -> Features -> team_page): chats between people - direct messages and groups.
// Any message (or a summary written by Claude) can be sent to a session, existing or new. Chats go straight to the
// other people's servers (Friends).
// The open chat is in the URL (?chat=<id>), the first one when none is (not on touch). The chats are the
// second-level sidebar (PageList). Touch: the chats are the page itself until one is picked (then the chat, with a
// back arrow to them; the left drawer has them too).
import * as React from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { MessageCircleMore, RefreshCw } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { PageList } from '@/components/shell/PageList'
import { useCompact } from '@/stores/media'
import { ChatView } from './Chat'
import { TeamSide } from './Side'

export default function TeamPage() {
  const t = useT()
  const { data: team, isError, refetch, isFetching } = useTeam()
  const [params, setParams] = useSearchParams()
  // On touch the chats come first: opening the newest one by itself would also mark it read.
  const compact = useCompact()
  const chatId = params.get('chat') || (compact ? null : team?.chats[0]?.id) || null
  // Touch: a chat picked in the page's list is a step forward (the phone's back gesture returns to the chats).
  const navigate = useNavigate()
  const stepped = React.useRef(false)
  const open = (id: string | null) => {
    const step = compact && !!id && !params.get('chat')
    if (step) stepped.current = true
    setParams(id ? { chat: id } : {}, { replace: !step })
  }
  const back = () => {
    if (!stepped.current) return open(null)
    stepped.current = false
    navigate(-1)
  }
  const pick = compact && !chatId
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
          <PageList id="team" label={t('team.title')} inline={pick}>
            <TeamSide team={team} active={chatId} onOpen={open} />
          </PageList>
          {chatId ? (
            <ChatView key={chatId} team={team} chatId={chatId} onBack={compact ? back : undefined} />
          ) : pick ? null : (
            <div className="flex min-w-0 flex-1 items-center justify-center p-6">
              <EmptyState icon={MessageCircleMore} title={team?.chats.length ? t('team.pick') : t('team.empty')} description={team?.chats.length ? undefined : t('team.emptyDesc')} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
