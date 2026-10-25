// Team on every page (desktop, Settings -> Features -> team_page): the chats in a column on the right of the page,
// opened from the Team entry of the sidebar; it stays open from page to page (per browser).
import { useNavigate } from 'react-router'
import { Maximize2, X } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, Tooltip } from '@/components/ui'
import { ChatList, ChatView } from './Chat'
import { TeamEmpty, TeamMenu } from './TeamPage'
import { useTeamUI } from './store'

export function TeamPanel() {
  const t = useT()
  const navigate = useNavigate()
  const { data: team } = useTeam()
  const ui = useTeamUI()
  const chat = ui.chat && team?.chats.some((c) => c.id === ui.chat) ? ui.chat : null
  const tools = (
    <div className="flex items-center">
      <Tooltip content={t('team.fullPage')}>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={() => {
            ui.setOpen(false)
            navigate(chat ? `/team?chat=${chat}` : '/team')
          }}
          aria-label={t('team.fullPage')}
        >
          <Maximize2 className="size-3.5" />
        </Button>
      </Tooltip>
      <Button size="icon-sm" variant="ghost" onClick={() => ui.setOpen(false)} aria-label={t('common.close')}>
        <X />
      </Button>
    </div>
  )
  return (
    <aside className="flex w-[380px] shrink-0 flex-col border-l bg-background animate-in fade-in-0 slide-in-from-right-4">
      {team && !team.chats.length && !Object.values(team.people).some((p) => p.contact) ? (
        <>
          <div className="flex justify-end border-b p-1.5">{tools}</div>
          <TeamEmpty compact />
        </>
      ) : chat ? (
        <ChatView key={chat} team={team} chatId={chat} compact onBack={() => ui.setChat(null)} headerExtra={tools} />
      ) : (
        <>
          <div className="flex min-h-[var(--header-h)] items-center gap-2 border-b py-1.5 pr-1.5 pl-3.5">
            <span className="flex-1 text-[14.5px] font-semibold">{t('team.title')}</span>
            <TeamMenu compact />
            {tools}
          </div>
          <ChatList team={team} active={null} onOpen={ui.setChat} compact />
        </>
      )}
    </aside>
  )
}
