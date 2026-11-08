// Primary navigation — single source for the sidebar, the mobile tab bar, the palette and shortcuts.
import { Bot, FolderOpen, GitBranch, LayoutDashboard, ListChecks, Mail, MessagesSquare, Network, Settings, UsersRound, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'
import { useExtensions, useSettings } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** A sidebar row (pages, extensions, Help / Feedback / Settings): one look everywhere; `collapsed` = the folded icon bar. */
export const navRow = (collapsed: boolean, active?: boolean) =>
  cn(
    'group relative flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
    active && 'bg-accent text-foreground',
    // folded icon bar: 44 px square targets, bigger icons (whatever size the row's own icon asks for)
    collapsed && 'h-11 justify-center px-0 [&>svg]:size-[22px]',
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
  /** shown only when this setting is on (Settings -> Features); hidden while the settings load */
  setting?: FeatureSetting
  /** sidebar block: the pages (the user may reorder them by dragging, with the pinned extension pages), or Settings, always last */
  group: NavGroup
}

export type NavGroup = 'main' | 'end'

/** `data-tour` id of a nav item (guided tour targets): nav-dashboard, nav-sessions… */
export const navTourId = (n: NavItem) => `nav-${n.to === '/' ? 'dashboard' : n.to.slice(1)}`

/** Every page in its sidebar order (the palette, the shortcuts and the touch menu follow it). Optional pages are
 *  listed only when switched on (Settings -> Features). The user reorders the pages by dragging them in the sidebar
 *  (settings `sidebar_order`, see orderEntries); Settings always stays last. */
export const NAV: NavItem[] = [
  { to: '/', label: 'nav.home', icon: LayoutDashboard, key: 'd', end: true, group: 'main' },
  { to: '/sessions', label: 'nav.sessions', icon: MessagesSquare, key: 's', group: 'main' },
  { to: '/agents', label: 'nav.agents', icon: Bot, key: 'a', setting: 'agents_page', group: 'main' },
  { to: '/tasks', label: 'nav.tasks', icon: ListChecks, key: 't', setting: 'tasks_page', group: 'main' },
  { to: '/team', label: 'nav.team', icon: UsersRound, key: 'm', setting: 'team_page', group: 'main' },
  { to: '/mail', label: 'nav.mail', icon: Mail, key: 'e', setting: 'mail_page', group: 'main' },
  { to: '/infra', label: 'nav.infra', icon: Network, key: 'i', setting: 'infra_page', group: 'main' },
  { to: '/git', label: 'nav.git', icon: GitBranch, key: 'b', setting: 'git_page', group: 'main' },
  { to: '/files', label: 'nav.files', icon: FolderOpen, key: 'f', group: 'main' },
  { to: '/settings', label: 'nav.settings', icon: Settings, key: ',', group: 'end' },
]

/** A pinned extension page: a row among the pages (sidebar, touch menu, palette); `extensions.pinned` says which. */
export type PinnedPage = { to: string; id: string; name: string; icon: string }

/** One row of the page list: an app page or a pinned extension page. */
export type NavEntry = { to: string; page: NavItem; ext?: undefined } | { to: string; ext: PinnedPage; page?: undefined }

/** The pages and the pinned extension pages in the user's order (settings `sidebar_order`, routes and `/x/<id>`):
 *  the saved routes first; a page it does not mention (switched on later, new in an update) right after the page it
 *  follows in NAV; a pinned page it does not mention at the end, in its pin order. Settings is not part of it. */
export function orderEntries(items: NavItem[], pins: PinnedPage[], order: string[] | undefined): NavEntry[] {
  const pages: NavEntry[] = items.filter((n) => n.group === 'main').map((page) => ({ to: page.to, page }))
  const known = new Map<string, NavEntry>([...pages, ...pins.map((ext) => ({ to: ext.to, ext }))].map((e) => [e.to, e]))
  const out = [...new Set(order || [])].map((to) => known.get(to)).filter((e): e is NavEntry => !!e)
  pages.forEach((e, i) => {
    if (out.includes(e)) return
    const before = pages.slice(0, i).reverse().find((p) => out.includes(p))
    out.splice(before ? out.indexOf(before) + 1 : 0, 0, e)
  })
  for (const e of known.values()) if (e.ext && !out.includes(e)) out.push(e)
  return out
}

/** The page extensions pinned to the sidebar, in their pin order. */
export function usePinnedPages(): PinnedPage[] {
  const { data } = useExtensions()
  return (data || [])
    .filter((e) => e.type === 'page' && e.enabled && !e.error && e.pinned)
    .sort((a, b) => (a.pin_order ?? 1e9) - (b.pin_order ?? 1e9) || a.name.localeCompare(b.name))
    .map((e) => ({ to: `/x/${e.id}`, id: e.id, name: e.name, icon: e.icon }))
}

/** The pages shown on this install (optional ones only once switched on). */
function usePages(): { pages: NavItem[]; order: string[] | undefined } {
  const { data: s } = useSettings()
  return { pages: NAV.filter((n) => !n.setting || !!s?.[n.setting]), order: s?.sidebar_order }
}

/** The pages shown on this install, in the user's order, Settings last (touch menu, palette, shortcuts). */
export function useNav(): NavItem[] {
  const { pages, order } = usePages()
  return [...orderEntries(pages, [], order).map((e) => e.page!), ...pages.filter((n) => n.group !== 'main')]
}

/** The sidebar's list: pages and pinned extension pages mixed in the user's order, then the `end` items (Settings). */
export function useNavEntries(): { entries: NavEntry[]; end: NavItem[] } {
  const { pages, order } = usePages()
  const pins = usePinnedPages()
  return { entries: orderEntries(pages, pins, order), end: pages.filter((n) => n.group !== 'main') }
}
