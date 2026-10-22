import { Link } from 'react-router'
import { Blocks, ChevronRight, Pin, PinOff, Settings2 } from 'lucide-react'
import { useExtensions, usePinExtension } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, EmptyState, NamedIcon, Skeleton, Tooltip } from '@/components/ui'
import { Page } from '@/components/shell/Page'

/** /x - every page added by an extension; pin one to give it its own sidebar entry. */
export default function ExtensionsHub() {
  const t = useT()
  const { data, isLoading } = useExtensions()
  const pin = usePinExtension()
  const pages = (data || []).filter((e) => e.type === 'page' && e.enabled && !e.error)
  return (
    <Page
      title={t('ext.hubTitle')}
      description={t('ext.hubDesc')}
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to="/settings/extensions">
            <Settings2 /> {t('ext.manage')}
          </Link>
        </Button>
      }
    >
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
      ) : !pages.length ? (
        <EmptyState
          icon={Blocks}
          title={t('ext.hubEmpty')}
          description={t('ext.emptyDesc')}
          action={
            <Button asChild>
              <Link to="/settings/extensions">{t('ext.manage')}</Link>
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {pages.map((x) => (
            <li key={x.id} className="group relative flex items-center gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted/50">
                <NamedIcon name={x.icon} className="size-5 text-primary" />
              </span>
              <Link to={`/x/${x.id}`} className="min-w-0 flex-1 outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring">
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
      )}
    </Page>
  )
}
