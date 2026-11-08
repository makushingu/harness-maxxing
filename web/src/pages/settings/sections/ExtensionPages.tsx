import { Link } from 'react-router'
import { Blocks, ChevronRight, Pin, PinOff } from 'lucide-react'
import { useExtensions, usePinExtension } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState, NamedIcon, Skeleton, Tooltip } from '@/components/ui'

/** Every page added by an extension (enabled, loaded): open it, or pin it to give it its own sidebar entry.
 *  Settings -> Extensions is its only place (/x redirects there; /x/<id> still opens a page). */
export function ExtensionPages() {
  const t = useT()
  const { data, isLoading } = useExtensions()
  const pin = usePinExtension()
  const pages = (data || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  if (isLoading)
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-20 rounded-xl" />
      </div>
    )
  if (!pages.length) return <EmptyState compact icon={Blocks} title={t('ext.hubEmpty')} description={t('ext.emptyDesc')} />
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {pages.map((x) => (
        <li key={x.id} className="group relative flex items-center gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted/50">
            <NamedIcon name={x.icon} className="size-5 text-primary" />
          </span>
          <Link to={`/x/${x.id}`} className="min-w-0 flex-1 outline-none pointer-coarse:min-h-10 after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring">
            <span className="block truncate text-sm font-medium">{x.name}</span>
            <span className="block truncate font-mono text-xs text-muted-foreground">v{x.version}</span>
          </Link>
          <Tooltip content={x.pinned ? t('ext.unpin') : t('ext.pin')}>
            <Button
              variant="ghost"
              size="icon-sm"
              className="relative z-10 text-muted-foreground"
              aria-label={x.pinned ? t('ext.unpin') : t('ext.pin')}
              aria-pressed={!!x.pinned}
              onClick={() => pin.mutate({ id: x.id, pinned: !x.pinned })}
            >
              {x.pinned ? <PinOff /> : <Pin />}
            </Button>
          </Tooltip>
          <ChevronRight className="size-4 text-muted-foreground" />
        </li>
      ))}
    </ul>
  )
}
