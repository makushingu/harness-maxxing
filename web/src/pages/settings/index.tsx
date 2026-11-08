// /settings/:section — left sub-nav on desktop, scrollable top tabs on mobile.
// Each section is its own component in ./sections/*.tsx (Telegram/Backup/Claude reuse src/features).
import * as React from 'react'
import { Navigate, NavLink, useLocation, useParams } from 'react-router'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { PageHeader, useDocumentTitle } from '@/components/shell/Page'
import { SECTION_MOVED, SETTINGS_GROUPS, SETTINGS_SECTIONS, type SettingsSectionId } from './sections'
import { GeneralSection } from './sections/General'
import { ProfileSection } from './sections/Profile'
import { FeaturesSection } from './sections/Features'
import { SecuritySection } from './sections/Security'
import { ClaudeSection } from './sections/Claude'
import { TelegramSection } from './sections/Telegram'
import { BackupSection } from './sections/Backup'
import { VoiceSection } from './sections/Voice'
import { KeysSection } from './sections/Keys'
import { McpSection } from './sections/Mcp'
import { ExtensionsSection } from './sections/Extensions'
import { SystemSection } from './sections/System'
import { TrashSection } from './sections/Trash'
import { ProjectsSection } from './sections/Projects'
import { NotificationsSection } from './sections/Notifications'
import { UsageSection } from './sections/Usage'
import { AboutSection } from './sections/About'
import { MemorySection } from './sections/Memory'
import { UpdatesSection } from './sections/Updates'

// The crons section is a whole page (list, history, editor): its own chunk, loaded when it opens.
const CronsSection = React.lazy(() => import('@/pages/crons'))

const COMPONENTS: Record<SettingsSectionId, React.ComponentType> = {
  general: GeneralSection,
  profile: ProfileSection,
  features: FeaturesSection,
  notifications: NotificationsSection,
  usage: UsageSection,
  about: AboutSection,
  memory: MemorySection,
  security: SecuritySection,
  claude: ClaudeSection,
  telegram: TelegramSection,
  voice: VoiceSection,
  backup: BackupSection,
  keys: KeysSection,
  mcp: McpSection,
  extensions: ExtensionsSection,
  packs: ProjectsSection,
  trash: TrashSection,
  system: SystemSection,
  updates: UpdatesSection,
  crons: CronsSection,
}

export default function SettingsPage() {
  const t = useT()
  const { section = 'general' } = useParams()
  const { search } = useLocation()
  const meta = SETTINGS_SECTIONS.find((s) => s.id === section)
  useDocumentTitle(meta ? `${t(meta.label)} · ${t('nav.settings')}` : t('nav.settings'))
  const tabs = React.useRef<HTMLUListElement>(null)
  const side = React.useRef<HTMLElement>(null)
  const mark = React.useRef<HTMLSpanElement>(null)
  // phones: the next section slides in from the side of its tab (decided once per section change, so a
  // re-render during the animation does not cut it)
  const slide = React.useRef({ section, cls: '' })
  if (slide.current.section !== section) {
    const from = SETTINGS_SECTIONS.findIndex((s) => s.id === slide.current.section)
    const to = SETTINGS_SECTIONS.findIndex((s) => s.id === section)
    slide.current = { section, cls: from < 0 || to < 0 ? '' : to > from ? 'max-md:animate-[mx-slide-x-r_240ms_cubic-bezier(0.22,1,0.36,1)]' : 'max-md:animate-[mx-slide-x-l_240ms_cubic-bezier(0.22,1,0.36,1)]' }
  }
  React.useLayoutEffect(() => {
    // The highlight slides to the active section (measured: group headings sit between the rows).
    const item = side.current?.querySelector<HTMLElement>('[aria-current=page]')
    const m = mark.current
    if (m) {
      const first = m.style.opacity !== '1' // no slide from the top when the page opens
      if (first) m.style.transition = 'none'
      m.style.opacity = item ? '1' : '0'
      if (item) m.style.transform = `translateY(${item.offsetTop}px)`
      if (first) {
        void m.offsetHeight
        m.style.transition = ''
      }
    }
  }, [section])
  React.useEffect(() => {
    // Keep the active mobile tab visible (horizontal scroll only, never moves the page).
    const ul = tabs.current
    const el = ul?.querySelector<HTMLElement>('[data-active]')
    if (ul && el) ul.scrollTo({ left: el.offsetLeft - ul.clientWidth / 2 + el.clientWidth / 2, behavior: 'smooth' })
    // Desktop list taller than the window: it scrolls on its own; keep the active section in it (never moves the page).
    const nav = side.current
    const item = nav?.querySelector<HTMLElement>('[aria-current=page]')
    if (nav && item && nav.scrollHeight > nav.clientHeight) {
      const top = item.offsetTop, bottom = top + item.offsetHeight
      if (top < nav.scrollTop) nav.scrollTop = top
      else if (bottom > nav.scrollTop + nav.clientHeight) nav.scrollTop = bottom - nav.clientHeight
    }
  }, [section])
  if (!meta) {
    const moved = SECTION_MOVED[section]
    if (moved) {
      const [path, hash = ''] = moved.split('#')
      return <Navigate to={{ pathname: path, search, hash }} replace />
    }
    return <Navigate to="/settings/general" replace />
  }
  const Cmp = COMPONENTS[meta.id]
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title={t('nav.settings')} sensitiveTitle={t('nav.settings')} />
      {/* Mobile tabs: same order as the column, a thin bar between groups */}
      <nav aria-label={t('nav.settings')} className="sticky top-[calc(var(--header-h)+var(--safe-top))] z-10 -mt-px border-b bg-background md:hidden">
        <ul ref={tabs} className="flex items-center gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none]">
          {SETTINGS_SECTIONS.map((s, i) => (
            <React.Fragment key={s.id}>
              {i > 0 && SETTINGS_SECTIONS[i - 1].group !== s.group && <li aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border" />}
              <li className="shrink-0">
                <NavLink
                  to={`/settings/${s.id}`}
                  data-active={s.id === section || undefined}
                  className={({ isActive }) =>
                    cn('flex h-9 max-md:h-10 pointer-coarse:h-10 items-center rounded-full px-3.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors duration-200', isActive && 'bg-secondary text-foreground')
                  }
                >
                  {t(s.label)}
                </NavLink>
              </li>
            </React.Fragment>
          ))}
        </ul>
      </nav>
      <div className="mx-auto flex w-full max-w-6xl flex-1 gap-10 px-4 py-6 md:px-6 md:py-8">
        <nav
          ref={side}
          aria-label={t('nav.settings')}
          className="sticky top-[calc(var(--header-h)+2rem)] -m-1 hidden max-h-[calc(100dvh-var(--header-h)-4rem-var(--safe-bottom))] w-54 shrink-0 self-start overflow-y-auto overscroll-contain p-1 [scrollbar-width:thin] md:block"
        >
          <div className="relative grid gap-4">
            <span
              ref={mark}
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 h-9 pointer-coarse:h-10 rounded-md bg-accent opacity-0 transition-transform duration-[260ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none"
            />
            {SETTINGS_GROUPS.map((g) => (
              <div key={g.id} className="grid gap-0.5">
                <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground/80 uppercase">{t(g.label)}</div>
                <ul className="grid gap-0.5">
                  {SETTINGS_SECTIONS.filter((s) => s.group === g.id).map((s) => (
                    <li key={s.id}>
                      <NavLink
                        to={`/settings/${s.id}`}
                        className={({ isActive }) =>
                          cn(
                            'relative flex h-9 pointer-coarse:h-10 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground outline-none transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                            isActive && 'font-medium text-foreground hover:bg-transparent',
                          )
                        }
                      >
                        <s.icon className="size-4" />
                        {t(s.label)}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </nav>
        <div className={cn('min-w-0 flex-1', slide.current.cls)} key={section}>
          <div className="mx-rise mb-6 grid gap-1">
            <h2 className="text-xl font-semibold tracking-tight">{t(meta.label)}</h2>
            <p className="text-sm text-muted-foreground">{t(meta.description)}</p>
          </div>
          <React.Suspense fallback={null}>
            <Cmp />
          </React.Suspense>
        </div>
      </div>
    </div>
  )
}
