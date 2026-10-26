// Team on every page (desktop, Settings -> Features -> team_page): the chats in a column on the right of the page,
// opened from the Team entry of the sidebar; it stays open from page to page, at the width the user dragged it to
// (per browser).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Maximize2, X } from 'lucide-react'
import { useTeam } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, Tooltip } from '@/components/ui'
import { ChatView } from './Chat'
import { TeamSide } from './Side'
import { PANEL_W, useTeamUI } from './store'

/** Drag the left edge to resize (double-click: back to the default width). */
function ResizeEdge({ panel }: { panel: React.RefObject<HTMLElement | null> }) {
  const t = useT()
  const setWidth = useTeamUI((s) => s.setWidth)
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('team.resize')}
      title={t('team.resize')}
      onDoubleClick={() => setWidth(null)}
      onPointerDown={(e) => {
        const el = panel.current
        if (!el || e.button !== 0) return
        e.preventDefault()
        const target = e.currentTarget
        target.setPointerCapture(e.pointerId)
        const startX = e.clientX
        const startW = el.getBoundingClientRect().width
        const max = Math.min(PANEL_W.max, window.innerWidth * 0.6)
        let w = startW
        const onMove = (ev: PointerEvent) => {
          w = Math.max(PANEL_W.min, Math.min(max, startW + startX - ev.clientX))
          el.style.width = `${w}px`
        }
        const onUp = () => {
          target.removeEventListener('pointermove', onMove)
          target.removeEventListener('pointerup', onUp)
          target.removeEventListener('pointercancel', onUp)
          document.body.style.cursor = ''
          document.body.style.userSelect = ''
          setWidth(w)
        }
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
        target.addEventListener('pointermove', onMove)
        target.addEventListener('pointerup', onUp)
        target.addEventListener('pointercancel', onUp)
      }}
      className="absolute inset-y-0 -left-1 z-20 w-2 cursor-col-resize touch-none after:absolute after:inset-y-0 after:left-[3px] after:w-[3px] after:transition-colors hover:after:bg-primary/40 active:after:bg-primary/60"
    />
  )
}

export function TeamPanel() {
  const t = useT()
  const navigate = useNavigate()
  const { data: team } = useTeam()
  const ui = useTeamUI()
  const ref = React.useRef<HTMLElement>(null)
  const chat = ui.chat && team?.chats.some((c) => c.id === ui.chat) ? ui.chat : null
  const tools = (
    <div className="flex shrink-0 items-center">
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
    <aside
      ref={ref}
      style={{ width: `min(${ui.width}px, 60vw)` }}
      className="relative flex min-w-0 shrink-0 flex-col border-l bg-background animate-in fade-in-0 slide-in-from-right-4"
    >
      <ResizeEdge panel={ref} />
      {chat ? (
        <ChatView key={chat} team={team} chatId={chat} compact onBack={() => ui.setChat(null)} headerExtra={tools} />
      ) : (
        <>
          <div className="flex min-h-[var(--header-h)] items-center gap-2 border-b py-1.5 pr-1.5 pl-3.5">
            <span className="flex-1 text-[14.5px] font-semibold">{t('team.title')}</span>
            {tools}
          </div>
          <TeamSide team={team} active={null} onOpen={ui.setChat} compact />
        </>
      )}
    </aside>
  )
}
