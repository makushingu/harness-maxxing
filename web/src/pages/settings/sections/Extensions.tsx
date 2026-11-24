// Settings -> Widgets, Pages and Agents views (2.0.0a132, were one Extensions list; views apart since 2.0.0a169, as on
// Community): the extensions of <workspace>/extensions, each in the section of what it brings (a page that also
// brings an Agents view shows in both). Themes: Themes.tsx.
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

type Kind = 'widgets' | 'pages' | 'views'
const inKind = (x: Extension, k: Kind) => (k === 'views' ? !!x.agents_view || x.type === 'view' : k === 'widgets' ? x.type === 'widget' : x.type !== 'widget' && x.type !== 'view')   // pages: also a wrong type, to show its error
const TEXT = {
  widgets: { prompt: 'ext.newWidgetPrompt', add: 'ext.newWidget', empty: 'ext.emptyWidgets', emptyDesc: 'ext.emptyWidgetsDesc', community: 'ext.communityWidgets', type: 'widget' },
  pages: { prompt: 'ext.newPagePrompt', add: 'ext.newPage', empty: 'ext.emptyPages', emptyDesc: 'ext.emptyPagesDesc', community: 'ext.communityPages', type: 'page' },
  views: { prompt: 'ext.newViewPrompt', add: 'ext.newView', empty: 'ext.emptyViews', emptyDesc: 'ext.emptyViewsDesc', community: 'ext.communityViews', type: 'view' },
} as const

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

export function ViewsSection() {
  const t = useT()
  return (
    <ExtensionList
      kind="views"
      extra={
        <Button variant="outline" size="sm" asChild>
          <Link to="/agents"><ExternalLink /> {t('ext.openAgents')}</Link>
        </Button>
      }
    />
  )
}

/** A link to the community catalogue (on the website, on purpose: nothing is installed from here). */
export function CommunityLink({ text, type }: { text: string; type?: string }) {
  return (
    <p className="flex items-center gap-1.5 px-1 text-[13px] text-muted-foreground">
      <Users className="size-3.5 shrink-0" />
      <span>
        {text}{' '}
        <a href={type ? `${COMMUNITY_URL}?type=${type}` : COMMUNITY_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline pointer-coarse:min-h-10">
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
  const tx = TEXT[kind]
  return (
    <SectionStack>
      <SettingsCard
        title={t('ext.installedTitle')}
        description={t('ext.installedDesc')}
        actions={
          <>
            {extra}
            <Button variant="outline" size="sm" onClick={() => navigate(draftUrl(topic, t(tx.prompt)))}>
              <Plus /> {t(tx.add)}
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
          <EmptyState compact icon={Blocks} title={t(tx.empty)} description={t(tx.emptyDesc)} />
        ) : (
          <ul className="divide-y border-t">
            {data.map((x) => (
              <li key={x.id} className="flex items-start gap-3 px-4 py-3.5">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted">
                  <NamedIcon name={x.icon} className="size-4.5 text-muted-foreground" />
                </span>
                <div className="grid min-w-0 flex-1 gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{x.name}</span>
                    {kind === 'views' && x.type !== 'view' && <Badge variant="muted">{t(x.type === 'widget' ? 'ext.alsoWidget' : 'ext.alsoPage')}</Badge>}
                    {kind !== 'views' && !!x.agents_view && <Badge variant="muted">{t('ext.view')}</Badge>}
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
                  {kind === 'pages' && x.enabled && !x.error && (
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
      <CommunityLink text={t(tx.community)} type={tx.type} />
    </SectionStack>
  )
}
