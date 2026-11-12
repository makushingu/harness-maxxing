// Settings -> Widgets and Settings -> Pages (2.0.0a132, were one Extensions list): the extensions of
// <workspace>/extensions, each in the section of what it brings (an extension with an Office view shows in Pages too).
// The community catalogue stays on the website: only a link here.
import * as React from 'react'
import { Link, useNavigate } from 'react-router'
import { AlertTriangle, Blocks, ExternalLink, Pencil, Plus, RefreshCw, Users } from 'lucide-react'
import { draftUrl } from '@/features/agents/EditWithClaude'
import type { Extension } from '@/lib/types'
import { COMMUNITY_URL } from './About'
import { useExtensions, usePinExtension, useReloadExtensions, useToggleExtension } from '@/lib/queries'
import { useT } from '@/i18n'
import { Badge, Button, EmptyState, NamedIcon, Skeleton, Switch, toast } from '@/components/ui'
import { SettingsCard, SectionStack } from './ui'
import { useHarnessTopic } from './harnessTopic'

type Kind = 'widgets' | 'pages'
const inKind = (x: Extension, k: Kind) => (k === 'widgets' ? x.type === 'widget' : x.type !== 'widget' || !!x.agents_view)

export function WidgetsSection() {
  const t = useT()
  return (
    <ExtensionList
      kind="widgets"
      extra={
        <Button variant="outline" size="sm" asChild>
          <Link to="/?edit=1"><Pencil /> {t('ext.customizeDashboard')}</Link>
        </Button>
      }
    />
  )
}

export function PagesSection() {
  return <ExtensionList kind="pages" />
}

/** A link to the community catalogue (on the website, on purpose: nothing is installed from here). */
export function CommunityLink({ text }: { text: string }) {
  return (
    <p className="flex items-center gap-1.5 px-1 text-[13px] text-muted-foreground">
      <Users className="size-3.5 shrink-0" />
      <span>
        {text}{' '}
        <a href={COMMUNITY_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline pointer-coarse:min-h-10">
          harness-maxxing.com/community <ExternalLink className="size-3" />
        </a>
      </span>
    </p>
  )
}

function ExtensionList({ kind, extra }: { kind: Kind; extra?: React.ReactNode }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: all, isLoading } = useExtensions()
  const data = all?.filter((x) => inKind(x, kind))
  const toggle = useToggleExtension()
  const pin = usePinExtension()
  const reload = useReloadExtensions()
  const topic = useHarnessTopic()
  return (
    <SectionStack>
      <SettingsCard
        title={t('ext.installedTitle')}
        description={t('ext.installedDesc')}
        actions={
          <>
            {extra}
            {kind === 'pages' && (
              // the Extensions page (/x) lists every page; the sidebar shows only the pinned ones
              <Button variant="outline" size="sm" onClick={() => navigate('/x')}>
                <Blocks /> {t('ext.allPages')}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => navigate(draftUrl(topic, t(kind === 'widgets' ? 'ext.newWidgetPrompt' : 'ext.newPagePrompt')))}>
              <Plus /> {t(kind === 'widgets' ? 'ext.newWidget' : 'ext.newPage')}
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
          <EmptyState compact icon={Blocks} title={t(kind === 'widgets' ? 'ext.emptyWidgets' : 'ext.emptyPages')} description={t(kind === 'widgets' ? 'ext.emptyWidgetsDesc' : 'ext.emptyPagesDesc')} />
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
                    {kind === 'pages' && !!x.agents_view && <Badge variant="muted">{t('ext.view')}</Badge>}
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
                  {x.type === 'page' && x.enabled && !x.error && (
                    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                      <Link to={`/x/${x.id}`} className="inline-flex w-fit items-center gap-1 pointer-coarse:min-h-10 text-[13px] font-medium text-primary hover:underline">
                        {t('ext.open')} <ExternalLink className="size-3" />
                      </Link>
                      <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-muted-foreground">
                        <Switch checked={!!x.pinned} onCheckedChange={(v) => pin.mutate({ id: x.id, pinned: v })} />
                        {t('ext.sidebar')}
                      </label>
                    </div>
                  )}
                </div>
                <Switch checked={x.enabled} onCheckedChange={(v) => toggle.mutate({ id: x.id, enabled: v })} aria-label={`${t('ext.enable')} ${x.name}`} className="mt-1" />
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>
      <CommunityLink text={t(kind === 'widgets' ? 'ext.communityWidgets' : 'ext.communityPages')} />
    </SectionStack>
  )
}
