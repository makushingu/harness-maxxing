// The sidebar's Help row (and the touch menu's Help entry): the docs, the keyboard shortcuts, the guided tour and
// Feedback, gathered behind one entry.
import { useNavigate } from 'react-router'
import { BookOpen, CircleHelp, Compass, Keyboard, MessageSquareText, type LucideIcon } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { startTour } from '@/tour/store'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Tooltip } from '@/components/ui'
import { iconBtn, navRow } from './nav'
import { useShortcutsDialog } from './shortcuts-store'
import { useFeedbackDialog } from './feedback-store'

export type HelpAction = { id: string; label: string; icon: LucideIcon; run: () => void }

/** The Help entries. Keyboard shortcuts only with a mouse or a trackpad around (they need a keyboard). */
export function useHelpActions(): HelpAction[] {
  const t = useT()
  const navigate = useNavigate()
  const keyboard = typeof window !== 'undefined' && window.matchMedia('(any-pointer: fine)').matches
  return [
    { id: 'docs', label: t('nav.docs'), icon: BookOpen, run: () => navigate('/docs') },
    ...(keyboard ? [{ id: 'shortcuts', label: t('shortcuts.title'), icon: Keyboard, run: () => useShortcutsDialog.getState().setOpen(true) }] : []),
    { id: 'tour', label: t('shell.replayTour'), icon: Compass, run: startTour },
    { id: 'feedback', label: t('shell.feedback'), icon: MessageSquareText, run: () => useFeedbackDialog.getState().setOpen(true) },
  ]
}

/** Help row of the sidebar: a small menu of the Help entries (folded: the icon). */
/** `compact`: the icon alone, on the sidebar's last line (unfolded bar). */
export function HelpMenu({ collapsed, compact }: { collapsed: boolean; compact?: boolean }) {
  const t = useT()
  const actions = useHelpActions()
  return (
    <DropdownMenu>
      <Tooltip content={collapsed || compact ? t('shell.help') : null} side={compact ? 'top' : 'right'}>
        <DropdownMenuTrigger
          className={compact ? iconBtn() : cn(navRow(collapsed), 'data-[state=open]:bg-accent data-[state=open]:text-foreground')}
          aria-label={t('shell.help')}
          data-testid="help-menu"
        >
          <CircleHelp className="size-[18px] shrink-0" strokeWidth={1.9} />
          {!collapsed && !compact && <span className="flex-1 truncate text-left">{t('shell.help')}</span>}
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent side="right" align="end" className="min-w-52" data-testid="help-menu-content">
        {actions.map((a) => (
          <DropdownMenuItem key={a.id} onSelect={a.run} data-help={a.id}>
            <a.icon /> {a.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
