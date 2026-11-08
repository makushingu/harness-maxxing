// /settings/:section — left sub-nav on desktop, scrollable top tabs on mobile, both under the SETTINGS_GROUPS headings.
// Each section is its own component in ./sections/*.tsx (Telegram/Backup/Claude reuse src/features).
import * as React from 'react'
import { Navigate, NavLink, useParams } from 'react-router'
import { ChevronRight } from 'lucide-react'
import { cn, store } from '@/lib/utils'
import { useT } from '@/i18n'
import { PageHeader, useDocumentTitle } from '@/components/shell/Page'
import { SETTINGS_GROUPS, SETTINGS_SECTIONS, type SettingsGroupId, type SettingsSectionId } from './sections'
import { GeneralSection } from './sections/General'
import { ProfileSection } from './sections/Profile'
import { LicenseSection } from './sections/License'
import { SupportSection } from './sections/Support'
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
import { ImportSection } from './sections/Import'
import { ProjectsSection } from './sections/Projects'
import { NotificationsSection } from './sections/Notifications'
import { StatsSection } from './sections/Stats'
import { MemorySection } from './sections/Memory'
import { UpdatesSection } from './sections/Updates'

// The crons section is a whole page (list, history, editor): its own chunk, loaded when it opens.
const CronsSection = React.lazy(() => import('@/pages/crons'))

const COMPONENTS: Record<Exclude<SettingsSectionId, 'docs'>, React.ComponentType> = {
  general: GeneralSection,
  profile: ProfileSection,
  license: LicenseSection,
  support: SupportSection,
  features: FeaturesSection,
  notifications: NotificationsSection,
  stats: StatsSection,
  memory: MemorySection,
  security: SecuritySection,
  claude: ClaudeSection,
  telegram: TelegramSection,
  voice: VoiceSection,
  backup: BackupSection,
  keys: KeysSection,
  mcp: McpSection,
  extensions: ExtensionsSection,
  import: ImportSection,
  packs: ProjectsSection,
  trash: TrashSection,
  system: SystemSection,
  updates: UpdatesSection,
  crons: CronsSection,
}

/** Folded headings the user opened (SETTINGS_GROUPS `folded`), kept across visits. */
const OPEN_KEY = 'mx-settings-open-groups'

function useOpenGroups(section: string) {
  const [open, setOpen] = React.useState<Set<SettingsGroupId>>(() => {
    try {
      return new Set(JSON.parse(store.get(OPEN_KEY) || '[]') as SettingsGroupId[])
    } catch {
      return new Set()
    }
  })
  // the section shown sits in a folded group (palette, link, bookmark): the group opens with it
  const current = SETTINGS_SECTIONS.find((s) => s.id === section)?.group
  const isOpen = (g: (typeof SETTINGS_GROUPS)[number]) => !g.folded || open.has(g.id) || g.id === current
  const toggle = (id: SettingsGroupId) => {
    // the group of the section shown stays open (folding it would hide where you are)
    if (id === current) return
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      store.set(OPEN_KEY, JSON.stringify([...next]))
      return next
    })
  }
  return { isOpen, toggle, current }
}

export default function SettingsPage() {
  const t = useT()
  const { section = 'general' } = useParams()
  const meta = SETTINGS_SECTIONS.find((s) => s.id === section)
  useDocumentTitle(meta ? `${t(meta.label)} · ${t('nav.settings')}` : t('nav.settings'))
  const tabs = React.useRef<HTMLUListElement>(null)
  const side = React.useRef<HTMLElement>(null)
  const list = React.useRef<HTMLDivElement>(null)
  const groups = useOpenGroups(section)
  const openKey = SETTINGS_GROUPS.map((g) => (groups.isOpen(g) ? 1 : 0)).join('')
  // the highlight slides to the active section: its place is measured, since headings and folded groups sit between rows
  const [mark, setMark] = React.useState<{ top: number; height: number; moved: boolean } | null>(null)
  // phones: the next section slides in from the side of its tab (decided once per section change, so a
  // re-render during the animation does not cut it)
  const slide = React.useRef({ section, cls: '' })
  if (slide.current.section !== section) {
    const from = SETTINGS_SECTIONS.findIndex((s) => s.id === slide.current.section)
    const to = SETTINGS_SECTIONS.findIndex((s) => s.id === section)
    slide.current = { section, cls: from < 0 || to < 0 ? '' : to > from ? 'max-md:animate-[mx-slide-x-r_240ms_cubic-bezier(0.22,1,0.36,1)]' : 'max-md:animate-[mx-slide-x-l_240ms_cubic-bezier(0.22,1,0.36,1)]' }
  }
  React.useLayoutEffect(() => {
    const item = list.current?.querySelector<HTMLElement>('[aria-current=page]')
    setMark((prev) => (item ? { top: item.offsetTop, height: item.offsetHeight, moved: !!prev } : null))
  }, [section, openKey])
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
  if (!meta || section === 'docs') return <Navigate to={section === 'docs' ? '/docs' : '/settings/general'} replace />
  const Cmp = COMPONENTS[section as Exclude<SettingsSectionId, 'docs'>]
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title={t('nav.settings')} sensitiveTitle={t('nav.settings')} />
      {/* Mobile tabs: one row, each heading before its sections; a folded heading is a chip that opens it */}
      <nav aria-label={t('nav.settings')} data-settings-nav="tabs" className="sticky top-[calc(var(--header-h)+var(--safe-top))] z-10 -mt-px border-b bg-background md:hidden">
        <ul ref={tabs} className="flex items-center gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none]">
          {SETTINGS_GROUPS.map((g, gi) => {
            const open = groups.isOpen(g)
            return (
              <React.Fragment key={g.id}>
                <li className={cn('flex shrink-0 items-center', gi > 0 && 'ml-2 border-l pl-3')}>
                  {g.folded ? (
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => groups.toggle(g.id)}
                      className="flex h-10 items-center gap-1 rounded-full border px-3 text-xs font-medium whitespace-nowrap text-muted-foreground"
                    >
                      {t(g.label)}
                      <ChevronRight className={cn('size-3.5 transition-transform duration-200', open && 'rotate-90')} />
                    </button>
                  ) : (
                    <span className="pr-1 text-xs font-medium whitespace-nowrap text-muted-foreground/70">{t(g.label)}</span>
                  )}
                </li>
                {open &&
                  SETTINGS_SECTIONS.filter((s) => s.group === g.id).map((s) => (
                    <li key={s.id} className="shrink-0">
                      <NavLink
                        to={`/settings/${s.id}`}
                        data-active={s.id === section || undefined}
                        className={({ isActive }) =>
                          cn('flex h-9 max-md:h-10 pointer-coarse:h-10 items-center rounded-full px-3.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors duration-200', s.id === 'support' && 'text-primary', isActive && 'bg-secondary text-foreground', isActive && s.id === 'support' && 'text-primary')
                        }
                      >
                        {t(s.label)}
                      </NavLink>
                    </li>
                  ))}
              </React.Fragment>
            )
          })}
        </ul>
      </nav>
      <div className="mx-auto flex w-full max-w-6xl flex-1 gap-10 px-4 py-6 md:px-6 md:py-8">
        <nav
          ref={side}
          aria-label={t('nav.settings')}
          data-settings-nav="list"
          className="sticky top-[calc(var(--header-h)+2rem)] -m-1 hidden max-h-[calc(100dvh-var(--header-h)-4rem-var(--safe-bottom))] w-54 shrink-0 self-start overflow-y-auto overscroll-contain p-1 [scrollbar-width:thin] md:block"
        >
          <div ref={list} className="relative grid gap-4">
            {mark && (
              <span
                aria-hidden
                className={cn('pointer-events-none absolute inset-x-0 top-0 rounded-md bg-accent motion-reduce:transition-none', mark.moved && 'transition-transform duration-[260ms] ease-[cubic-bezier(0.22,1,0.36,1)]')}
                style={{ height: mark.height, transform: `translateY(${mark.top}px)` }}
              />
            )}
            {SETTINGS_GROUPS.map((g) => {
              const open = groups.isOpen(g)
              const listId = `settings-group-${g.id}`
              return (
                <div key={g.id} className="grid gap-1">
                  {g.folded ? (
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-controls={listId}
                      onClick={() => groups.toggle(g.id)}
                      className="flex h-7 items-center justify-between gap-2 rounded-md px-2.5 text-xs font-medium text-muted-foreground/80 outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {t(g.label)}
                      <ChevronRight className={cn('size-3.5 transition-transform duration-200 motion-reduce:transition-none', open && 'rotate-90')} />
                    </button>
                  ) : (
                    <h3 className="flex h-7 items-center px-2.5 text-xs font-medium text-muted-foreground/80">{t(g.label)}</h3>
                  )}
                  {open && (
                    <ul id={listId} className="grid gap-0.5">
                      {SETTINGS_SECTIONS.filter((s) => s.group === g.id).map((s) => (
                        <li key={s.id}>
                          <NavLink
                            to={`/settings/${s.id}`}
                            className={({ isActive }) =>
                              cn(
                                'relative flex h-9 pointer-coarse:h-10 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground outline-none transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                                isActive && 'font-medium text-foreground hover:bg-transparent',
                                s.id === 'support' && 'font-medium text-primary hover:text-primary',
                              )
                            }
                          >
                            <s.icon className="size-4" />
                            {t(s.label)}
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
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
