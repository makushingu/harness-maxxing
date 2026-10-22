import { NavLink } from 'react-router'
import { Blocks } from 'lucide-react'
import { useExtensions } from '@/lib/queries'
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
 * Extension pages in the sidebar: one "Extensions" entry (the /x hub, with the count of unpinned pages),
 * then each pinned page right below it. Nothing is shown when no page extension is installed.
 */
export function SidebarExtensions({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const { data } = useExtensions()
  const pages = (data || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  if (!pages.length) return null
  const pinned = pages.filter((e) => e.pinned)
  const others = pages.length - pinned.length
  return (
    <div className={cn('grid gap-0.5 border-t border-sidebar-border px-3 pt-2 pb-2', collapsed && 'px-2.5')}>
      <Tooltip content={collapsed ? t('ext.hubTitle') : null} side="right">
        <NavLink to="/x" end className={item(collapsed)}>
          {({ isActive }) => (
            <>
              {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
              <Blocks className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
              {!collapsed && (
                <>
                  <span className="flex-1 truncate">{t('ext.hubTitle')}</span>
                  {others > 0 && <span className="rounded bg-muted px-1.5 text-[11px] font-semibold text-muted-foreground tabular-nums">{others}</span>}
                </>
              )}
            </>
          )}
        </NavLink>
      </Tooltip>
      {pinned.map((x) => (
        <Tooltip key={x.id} content={collapsed ? x.name : null} side="right">
          <NavLink to={`/x/${x.id}`} className={item(collapsed)}>
            {({ isActive }) => (
              <>
                {isActive && <span aria-hidden className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-primary" />}
                <NamedIcon name={x.icon} className={cn('size-[18px] shrink-0', isActive && 'text-primary')} strokeWidth={isActive ? 2.2 : 1.9} />
                {!collapsed && <span className="flex-1 truncate">{x.name}</span>}
              </>
            )}
          </NavLink>
        </Tooltip>
      ))}
    </div>
  )
}
