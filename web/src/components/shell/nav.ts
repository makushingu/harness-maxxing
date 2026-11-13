// Primary navigation — single source for the sidebar, the mobile tab bar, the palette and shortcuts.
import { Bot, FolderOpen, GitBranch, LayoutDashboard, ListChecks, Mail, MessagesSquare, Network, Settings, UsersRound, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'
import { useExtensions, useSettings } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** A sidebar row (pages, extensions, Help / Feedback / Settings): one look everywhere; `collapsed` = the folded icon bar. */
export const navRow = (collapsed: boolean, active?: boolean) =>
  cn(
    // `mx-nav-row`: 44 px tall while the bar is unfolded over the page too (globals.css), so no row moves when it
    // unfolds; the icon (18 px in every row) eases between its folded (20 px) and unfolded size instead of jumping,
    // by `transform: scale()` (composited, no layout or style per frame; Chromium never composites the independent
    // `scale` property on an <svg>). A fine stroke (1.7, 2 on the current page) whatever the icon's own
    // attribute, so every row of the bar has the same weight (folded, divided by the scale so it looks the same).
    'mx-nav-row group relative flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
    '[&>svg]:transition-transform [&>svg]:duration-300 [&>svg]:ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:[&>svg]:transition-none',
    // the highlight itself is ActiveMark's pill, so it can glide to the next row
    active ? 'isolate text-foreground' : '',
    collapsed ? (active ? '[&>svg]:[stroke-width:1.8]' : '[&>svg]:[stroke-width:1.53]') : active ? '[&>svg]:[stroke-width:2]' : '[&>svg]:[stroke-width:1.7]',
    // folded icon bar: 44 px square targets, slightly bigger icons (18 px scaled to 20 px); 36 px in a short window,
    // so every row still fits above the bottom block instead of being cut off
    collapsed && 'h-11 justify-center px-0 [&>svg]:[transform:scale(1.1112)] [@media(max-height:820px)]:h-9',
  )

/** An icon button of the sidebar's last line (Settings, theme, presentation mode, Help): same hover and focus as a row; 40 px to the finger. */
export const iconBtn = (active?: boolean) =>
  cn(
    'flex size-9 shrink-0 items-center pointer-coarse:size-10 justify-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-accent data-[state=open]:text-foreground [&_svg]:size-[18px] [&_svg]:[stroke-width:1.7]',
    active && 'bg-accent text-foreground [&_svg]:text-primary [&_svg]:[stroke-width:2]',
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
  /** shown only when this setting is on (Settings -> Features); hidden while the settings load unless `defaultOn` */
  setting?: FeatureSetting
  /** shown while the settings load (the page is on by default) */
  defaultOn?: boolean
  /** sidebar block: the pages (the user may reorder them by dragging), or Settings, always last */
  group: NavGroup
}

export type NavGroup = 'main' | 'end'

/** `data-tour` id of a nav item (guided tour targets): nav-dashboard, nav-sessions… */
export const navTourId = (n: NavItem) => `nav-${n.to === '/' ? 'dashboard' : n.to.slice(1)}`

/** Every page in its sidebar order (the palette, the shortcuts and the touch menu follow it). Optional pages are
 *  listed only when switched on (Settings -> Features). The user reorders the pages by dragging them in the sidebar
 *  (settings `sidebar_order`, see orderPages); Settings always stays last. */
export const NAV: NavItem[] = [
  { to: '/', label: 'nav.home', icon: LayoutDashboard, key: 'd', end: true, group: 'main' },
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

/** A pinned extension page: a row of the sidebar's Extensions folder (and of the palette); `extensions.pinned` says which. */
export type PinnedPage = { to: string; id: string; name: string; icon: string }

/** The pages in the user's order (settings `sidebar_order`, routes): the saved routes first; a page it does not
 *  mention (switched on later, new in an update) right after the page it follows in NAV. Settings is not part of it.
 *  Extension pages are not here: they sit in the Extensions folder, in their pin order. */
export function orderPages(items: NavItem[], order: string[] | undefined): NavItem[] {
  const pages = items.filter((n) => n.group === 'main')
  const known = new Map(pages.map((p) => [p.to, p]))
  const out = [...new Set(order || [])].map((to) => known.get(to)).filter((p): p is NavItem => !!p)
  pages.forEach((p, i) => {
    if (out.includes(p)) return
    const before = pages.slice(0, i).reverse().find((x) => out.includes(x))
    out.splice(before ? out.indexOf(before) + 1 : 0, 0, p)
  })
  return out
}

/** `items` in the user's order (settings `sidebar_order`), Settings last: the list of Settings -> Features. */
export function orderNav(items: NavItem[], order: string[] | undefined): NavItem[] {
  return [...orderPages(items, order), ...items.filter((n) => n.group !== 'main')]
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
  return { pages: NAV.filter((n) => !n.setting || (s ? !!s[n.setting] : !!n.defaultOn)), order: s?.sidebar_order }
}

/** The pages shown on this install, in the user's order, Settings last (touch menu, palette, shortcuts). */
export function useNav(): NavItem[] {
  const { pages, order } = usePages()
  return orderNav(pages, order)
}

/** The sidebar: the pages in the user's order, the pinned extension pages (its Extensions folder), then the `end`
 *  items (Settings). */
export function useNavEntries(): { pages: NavItem[]; pins: PinnedPage[]; end: NavItem[] } {
  const { pages, order } = usePages()
  const pins = usePinnedPages()
  return { pages: orderPages(pages, order), pins, end: pages.filter((n) => n.group !== 'main') }
}
