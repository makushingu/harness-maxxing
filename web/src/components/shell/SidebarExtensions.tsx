import { NavLink } from 'react-router'
import { Blocks, ChevronRight } from 'lucide-react'
import { useExtensions, useOrderPins } from '@/lib/queries'
import { useUI } from '@/stores/ui'
import { useDragOrder } from './dragOrder'
import { useT } from '@/i18n'
import { NamedIcon, Tooltip } from '@/components/ui'
import { cn } from '@/lib/utils'

const item = (collapsed: boolean) => ({ isActive }: { isActive: boolean }) =>
  cn(
    'group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
    isActive && 'bg-accent text-foreground',
    collapsed && 'justify-center px-0',
  )

/**
 * Extension pages in the sidebar: one "Extensions" row (the /x hub, without a counter: the count of unpinned pages
 * read like a notification, and the stock "Your pages" made it 1 on every install) that folds / unfolds the pinned
 * pages below it (this browser). The pinned pages keep the order they are dragged in (config extensions.pinned);
 * they can only be dragged among themselves. Nothing is shown when no page extension is installed.
 */
export function SidebarExtensions({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useExtensions()
  const open = useUI((s) => s.sidebarExtOpen)
  const toggle = useUI((s) => s.toggleSidebarExt)
  const orderPins = useOrderPins()
  const pages = (data || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  const pinned = pages.filter((e) => e.pinned).sort((a, b) => (a.pin_order ?? 1e9) - (b.pin_order ?? 1e9) || a.name.localeCompare(b.name))
  const drag = useDragOrder(
    pinned.map((x) => x.id),
    (order) => orderPins.mutate(order),
    'pins',
  )
  if (!pages.length) return null
  return (
    <div className={cn('grid gap-0.5 border-t border-sidebar-border px-3 pt-2 pb-2', collapsed && 'px-2.5')}>
      <div className="group/ext relative flex items-center">
        <Tooltip content={collapsed ? t('ext.hubTitle') : null} side="right">
          <NavLink to="/x" end className={(s) => cn(item(collapsed)(s), 'flex-1')}>
            {({ isActive }) => (
              <>
                {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
                <Blocks className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
                {!collapsed && <span className="flex-1 truncate">{t('ext.hubTitle')}</span>}
              </>
            )}
          </NavLink>
        </Tooltip>
        {!collapsed && pinned.length > 0 && (
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-label={open ? t('ext.foldPins') : t('ext.unfoldPins')}
            title={open ? t('ext.foldPins') : t('ext.unfoldPins')}
            className="absolute right-1 flex size-7 items-center justify-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-background/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight className={cn('size-4 transition-transform duration-200', open && 'rotate-90')} />
          </button>
        )}
      </div>
      {open &&
        drag.order.map((id) => {
          const x = pinned.find((p) => p.id === id)!
          return (
            <Tooltip key={x.id} content={collapsed ? x.name : null} side="right">
              <NavLink to={`/x/${x.id}`} className={item(collapsed)} {...drag.props(x.id)}>
                {({ isActive }) => (
                  <>
                    {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
                    <NamedIcon name={x.icon} className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
                    {!collapsed && <span className="flex-1 truncate">{x.name}</span>}
                  </>
                )}
              </NavLink>
            </Tooltip>
          )
        })}
    </div>
  )
}
