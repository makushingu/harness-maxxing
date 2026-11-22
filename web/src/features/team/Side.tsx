// The left part of Team (page) / the panel's home: two tabs, the chats and the friends.
import { MessageCircle, Users } from 'lucide-react'
import { useTeamConnections, type TeamState } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Segmented } from '@/components/ui'
import { ChatList } from './Chat'
import { ListChips } from '@/components/shell/PageList'
import { FriendsView } from './Friends'
import { unreadOf } from './people'
import { useTeamUI } from './store'

const Count = ({ n }: { n: number }) =>
  n ? <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground tabular-nums">{n}</span> : null

export function TeamSide({ team, active, onOpen, compact, query }: { team: TeamState | undefined; active: string | null; onOpen: (id: string) => void; compact?: boolean; /** the Team page (its list's search) */ query?: string }) {
  const t = useT()
  const tab = useTeamUI((s) => s.tab)
  const setTab = useTeamUI((s) => s.setTab)
  const { data: cx } = useTeamConnections()
  const unread = unreadOf(team)
  const requests = cx?.contacts.filter((x) => x.status === 'request').length || 0
  const open = (id: string) => {
    setTab('chats')
    onOpen(id)
  }
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {query !== undefined ? (
        // the page: the filters of a list, as on every page (Sessions, Agents)
        <div className="shrink-0 px-2 pt-2 pb-1.5">
          <ListChips
            label={t('team.title')}
            value={tab}
            onChange={setTab}
            items={[
              { key: 'chats', label: t('team.tab.chats'), count: unread },
              { key: 'friends', label: t('team.tab.friends'), count: requests },
            ]}
          />
        </div>
      ) : <div className={cn('flex shrink-0 items-center', compact ? 'px-2 pt-2' : 'px-3 pt-3')}>
        <Segmented
          size="sm"
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1 [&>button]:flex-1"
          options={[
            { value: 'chats', label: <>{t('team.tab.chats')} <Count n={unread} /></>, icon: <MessageCircle /> },
            { value: 'friends', label: <>{t('team.tab.friends')} <Count n={requests} /></>, icon: <Users /> },
          ]}
        />
      </div>}
      {tab === 'chats' ? (
        <ChatList team={team} active={active} onOpen={onOpen} onFriends={() => setTab('friends')} compact={compact} query={query} />
      ) : (
        <FriendsView team={team} onOpenChat={open} compact={compact} query={query} />
      )}
    </div>
  )
}
