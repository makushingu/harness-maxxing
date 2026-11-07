// Primary navigation — single source for the sidebar, the mobile tab bar, the palette and shortcuts.
import { Bot, FolderOpen, GitBranch, LayoutDashboard, ListChecks, Mail, MessagesSquare, Network, Settings, UsersRound, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'
import { useSettings } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** A sidebar row (pages, extensions, Help / Feedback / Settings): one look everywhere. */
export const navRow = (collapsed: boolean, active?: boolean) =>
  cn(
    'group relative flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
    active && 'bg-accent text-foreground',
    collapsed && 'justify-center px-0',
  )

type FeatureSetting = 'tasks_page' | 'git_page' | 'infra_page' | 'team_page' | 'agents_page' | 'mail_page'

export type NavItem = {
  to: string
  label: TKey
  /** label in the mobile tab bar when `label` is too long */
  short?: TKey
  icon: LucideIcon
  /** g + key */
  key: string
  end?: boolean
  /** shown only when this setting is on (Settings -> Features) */
  setting?: FeatureSetting
  /** shown while the settings load (optional pages only) */
  defaultOn?: boolean
  /** sidebar block: the pages (the user may reorder them by dragging), or Settings, always last (after the extensions) */
  group: NavGroup
}

export type NavGroup = 'main' | 'end'

/** `data-tour` id of a nav item (guided tour targets): nav-dashboard, nav-sessions… */
export const navTourId = (n: NavItem) => `nav-${n.to === '/' ? 'dashboard' : n.to.slice(1)}`

/** Every page in its sidebar order (the palette, the shortcuts and the touch menu follow it). Optional pages are
 *  listed only when switched on (Settings -> Features). The user reorders the pages by dragging them in the sidebar
 *  (settings `sidebar_order`, see orderNav); Settings always stays last. */
export const NAV: NavItem[] = [
  { to: '/', label: 'nav.dashboard', short: 'nav.home', icon: LayoutDashboard, key: 'd', end: true, group: 'main' },
  { to: '/sessions', label: 'nav.sessions', icon: MessagesSquare, key: 's', group: 'main' },
  { to: '/agents', label: 'nav.agents', icon: Bot, key: 'a', setting: 'agents_page', group: 'main' },
  { to: '/tasks', label: 'nav.tasks', icon: ListChecks, key: 't', setting: 'tasks_page', defaultOn: true, group: 'main' },
  { to: '/team', label: 'nav.team', icon: UsersRound, key: 'm', setting: 'team_page', group: 'main' },
  { to: '/mail', label: 'nav.mail', icon: Mail, key: 'e', setting: 'mail_page', group: 'main' },
  { to: '/infra', label: 'nav.infra', icon: Network, key: 'i', setting: 'infra_page', group: 'main' },
  { to: '/git', label: 'nav.git', icon: GitBranch, key: 'b', setting: 'git_page', group: 'main' },
  { to: '/files', label: 'nav.files', icon: FolderOpen, key: 'f', group: 'main' },
  { to: '/settings', label: 'nav.settings', icon: Settings, key: ',', group: 'end' },
]

/** `items` in the user's order (settings `sidebar_order`): the saved routes first, each page it does not mention
 *  (switched on later, new in an update) right after the page it follows in NAV. Settings always stays last. */
export function orderNav(items: NavItem[], order: string[] | undefined): NavItem[] {
  const main = items.filter((n) => n.group === 'main')
  const end = items.filter((n) => n.group !== 'main')
  if (!order?.length) return items
  const out = [...new Set(order)].map((to) => main.find((n) => n.to === to)).filter((n): n is NavItem => !!n)
  main.forEach((n, i) => {
    if (out.includes(n)) return
    const before = main.slice(0, i).reverse().find((p) => out.includes(p))
    out.splice(before ? out.indexOf(before) + 1 : 0, 0, n)
  })
  return [...out, ...end]
}

/** The pages shown on this install, in the user's order (sidebar, touch menu, palette, shortcuts). */
export function useNav(): NavItem[] {
  const { data: s } = useSettings()
  return orderNav(
    NAV.filter((n) => !n.setting || (s ? !!s[n.setting] : !!n.defaultOn)),
    s?.sidebar_order,
  )
}
