import { useNavigate } from 'react-router'
import { BookOpen, Compass, Download, Eye, EyeOff, GraduationCap, Keyboard, LogOut, Monitor, Moon, Settings, Sun, User } from 'lucide-react'
import { useLogout } from '@/lib/queries'
import { useUI, type Theme } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from '@/components/ui'
import { useShortcutsDialog } from './shortcuts-store'
import { startTour, useTutorialHref } from '@/tour/store'
import { installApp, useInstallMode } from '@/pwa'

const THEME_ICON: Record<Theme, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }

export function ThemeToggle({ collapsed }: { collapsed?: boolean }) {
  const t = useT()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const Icon = THEME_ICON[theme]
  return (
    <DropdownMenu>
      <Tooltip content={t('shell.theme')} side="right">
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('shell.theme')} className={cn(!collapsed && 'size-8')}>
            <Icon />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent side="top" align="start">
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
          <DropdownMenuRadioItem value="dark">{t('theme.dark')}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">{t('theme.light')}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">{t('theme.system')}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function PresentationToggle() {
  const t = useT()
  const on = useUI((s) => s.presentation)
  const set = useUI((s) => s.setPresentation)
  return (
    <Tooltip content={on ? t('presentation.off') : t('presentation.on')} side="right">
      <Button
        variant="ghost"
        size="icon-sm"
        className={cn('size-8', on && 'bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary')}
        aria-pressed={on}
        aria-label={t('presentation.label')}
        onClick={() => set(!on)}
      >
        {on ? <EyeOff /> : <Eye />}
      </Button>
    </Tooltip>
  )
}

export function UserMenu({ collapsed }: { collapsed?: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const logout = useLogout()
  const openShortcuts = useShortcutsDialog((s) => s.setOpen)
  const install = useInstallMode()
  const tutorial = useTutorialHref()
  return (
    <DropdownMenu>
      <Tooltip content={collapsed ? t('shell.account') : null} side="right">
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" className="size-8" aria-label={t('shell.account')}>
            <User />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent side="top" align="start" className="w-56">
        <DropdownMenuLabel>{t('shell.account')}</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => navigate('/settings/general')}>
          <Settings /> {t('nav.settings')}
        </DropdownMenuItem>
        {install && (
          <DropdownMenuItem onSelect={() => void installApp()}>
            <Download /> {t('pwa.install')}
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('help.title')}</DropdownMenuLabel>
        <DropdownMenuItem onSelect={startTour}>
          <Compass /> {t('tour.take')}
        </DropdownMenuItem>
        {tutorial && (
          <DropdownMenuItem onSelect={() => navigate(tutorial!)}>
            <GraduationCap /> {t('tour.tutorial')}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => navigate('/docs')}>
          <BookOpen /> {t('nav.docs')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => openShortcuts(true)}>
          <Keyboard /> {t('shortcuts.title')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => logout.mutate()}>
          <LogOut /> {t('auth.signOut')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
