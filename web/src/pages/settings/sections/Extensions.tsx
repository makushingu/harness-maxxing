import { Link } from 'react-router'
import { AlertTriangle, BookOpen, Blocks, RefreshCw } from 'lucide-react'
import { useExtensions, useReloadExtensions, useToggleExtension } from '@/lib/queries'
import { useT } from '@/i18n'
import { Badge, Button, EmptyState, NamedIcon, Skeleton, Switch, toast } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'
import { ExtensionPages } from './ExtensionPages'

export function ExtensionsSection() {
  const t = useT()
  const { data, isLoading } = useExtensions()
  const toggle = useToggleExtension()
  const reload = useReloadExtensions()
  return (
    <SectionStack>
      <SettingsCard title={t('setui.pages')} description={t('ext.hubDesc')}>
        <ExtensionPages />
      </SettingsCard>
      <SettingsCard
        title={t('ext.installed')}
        description={t('ext.installedDesc')}
        actions={
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/docs">
                <BookOpen /> {t('ext.docs')}
              </Link>
            </Button>
            <Button variant="outline" size="sm" loading={reload.isPending} onClick={() => reload.mutate(undefined, { onSuccess: () => toast.success(t('ext.reloaded')) })}>
              <RefreshCw /> {t('ext.reload')}
            </Button>
          </>
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : !data?.length ? (
          <EmptyState compact icon={Blocks} title={t('ext.empty')} description={t('ext.emptyDesc')} />
        ) : (
          <ul className="divide-y border-t">
            {data.map((x) => (
              <li key={x.id} className="flex items-start gap-3 px-4 py-3.5">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/50">
                  <NamedIcon name={x.icon} className="size-4.5 text-muted-foreground" />
                </span>
                <div className="grid min-w-0 flex-1 gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{x.name}</span>
                    <Badge variant="muted">{x.type === 'page' ? t('ext.page') : x.type === 'view' ? t('ext.view') : t('ext.widget')}</Badge>
                    {x.agents_view && x.type !== 'view' && <Badge variant="outline">{t('ext.view')}</Badge>}
                    <span className="font-mono text-xs text-muted-foreground">
                      {x.id} · v{x.version}
                    </span>
                    {x.has_api && <Badge variant="outline">API</Badge>}
                  </div>
                  {x.error && (
                    <p className="flex items-start gap-1.5 text-[13px] text-destructive">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                      <span className="font-mono break-all">{x.error}</span>
                    </p>
                  )}
                </div>
                <Switch checked={x.enabled} onCheckedChange={(v) => toggle.mutate({ id: x.id, enabled: v })} aria-label={`${t('ext.enable')} ${x.name}`} className="mt-1" />
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>
    </SectionStack>
  )
}
