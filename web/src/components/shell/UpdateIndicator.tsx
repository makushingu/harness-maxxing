import { ArrowUpCircle, RefreshCw } from 'lucide-react'
import { Link } from 'react-router'
import { applyUpdate, usePWA } from '@/pwa'
import { useVersion } from '@/lib/queries'
import { useT } from '@/i18n'
import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/utils'

/** Which update is pending: the web app was rebuilt on the server (reload), or the server can be updated. */
export function usePendingUpdate(): 'reload' | 'server' | null {
  const waiting = usePWA((s) => s.waiting)
  const { data: v } = useVersion()
  if (waiting) return 'reload'
  if (v?.behind) return 'server'
  return null
}

const row =
  'flex h-8 w-full items-center gap-3 rounded-md px-2.5 text-[12.5px] font-medium text-primary outline-none pointer-coarse:h-10 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring'

/** One discreet line above the health indicator - nothing at all when everything is up to date. */
export function UpdateIndicator({ collapsed }: { collapsed?: boolean }) {
  const t = useT()
  const pending = usePendingUpdate()
  if (!pending) return null
  const label = pending === 'reload' ? t('update.reload') : t('update.server')
  const Icon = pending === 'reload' ? RefreshCw : ArrowUpCircle
  const inner = (
    <>
      <span className="flex size-4 items-center justify-center">
        <Icon className="size-3.5" />
      </span>
      {!collapsed && <span className="truncate">{label}</span>}
    </>
  )
  return (
    <Tooltip content={collapsed ? label : null} side="right">
      {pending === 'reload' ? (
        <button type="button" onClick={applyUpdate} className={cn(row, collapsed && 'justify-center px-0')} aria-label={label}>
          {inner}
        </button>
      ) : (
        <Link to="/settings/system" className={cn(row, collapsed && 'justify-center px-0')} aria-label={label}>
          {inner}
        </Link>
      )}
    </Tooltip>
  )
}
