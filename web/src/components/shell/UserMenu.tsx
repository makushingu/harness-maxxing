import { Eye, EyeOff, Monitor, Moon, Sun } from 'lucide-react'
import { useUI, type Theme } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Tooltip,
} from '@/components/ui'

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
