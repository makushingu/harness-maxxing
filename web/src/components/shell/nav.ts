// Primary navigation — single source for the sidebar, the mobile tab bar, the palette and shortcuts.
import { Bot, FolderOpen, GitBranch, LayoutDashboard, ListChecks, Mail, MessagesSquare, Network, Settings, UsersRound, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'
import { useSettings } from '@/lib/queries'

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
  /** sidebar block: everyday pages, technical tools, then Settings (after the extension pages) */
  group: NavGroup
}

export type NavGroup = 'main' | 'tools' | 'end'

/** `data-tour` id of a nav item (guided tour targets): nav-dashboard, nav-sessions… */
export const navTourId = (n: NavItem) => `nav-${n.to === '/' ? 'dashboard' : n.to.slice(1)}`

/** Every page in its sidebar order (the palette, the shortcuts and the touch menu follow it). Optional pages are
 *  listed only when switched on (Settings -> Features); an empty group disappears with its separator. */
export const NAV: NavItem[] = [
  { to: '/', label: 'nav.dashboard', short: 'nav.home', icon: LayoutDashboard, key: 'd', end: true, group: 'main' },
  { to: '/sessions', label: 'nav.sessions', icon: MessagesSquare, key: 's', group: 'main' },
  { to: '/agents', label: 'nav.agents', icon: Bot, key: 'a', setting: 'agents_page', group: 'main' },
  { to: '/tasks', label: 'nav.tasks', icon: ListChecks, key: 't', setting: 'tasks_page', defaultOn: true, group: 'main' },
  { to: '/mail', label: 'nav.mail', icon: Mail, key: 'e', setting: 'mail_page', group: 'main' },
  { to: '/team', label: 'nav.team', icon: UsersRound, key: 'm', setting: 'team_page', group: 'main' },
  { to: '/files', label: 'nav.files', icon: FolderOpen, key: 'f', group: 'main' },
  { to: '/infra', label: 'nav.infra', icon: Network, key: 'i', setting: 'infra_page', group: 'tools' },
  { to: '/git', label: 'nav.git', icon: GitBranch, key: 'b', setting: 'git_page', group: 'tools' },
  { to: '/settings', label: 'nav.settings', icon: Settings, key: ',', group: 'end' },
]

/** The pages shown on this install, in order (sidebar, touch menu, palette, shortcuts). */
export function useNav(): NavItem[] {
  const { data: s } = useSettings()
  return NAV.filter((n) => !n.setting || (s ? !!s[n.setting] : !!n.defaultOn))
}
