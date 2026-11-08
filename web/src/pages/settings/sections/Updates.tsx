// Settings -> Updates: the installed version and the update itself (VersionCard), then every version of the product, newest first (CHANGELOG.md of the installed code, via
// GET /api/system/changelog). The "What's new" dialog shows only the versions this browser has not seen.
import * as React from 'react'
import { Search } from 'lucide-react'
import { useAllUpdates } from '@/lib/queries'
import { useT } from '@/i18n'
import { Badge, Input, Skeleton } from '@/components/ui'
import { Markdown } from '@/components/ui/markdown'
import { SHOW_LINK_CLASS, showcaseLink, showLinks } from '@/features/whatsnew/showcases'
import { useTour } from '@/tour/store'
import { SettingsCard, SectionStack } from './ui'
import { VersionCard } from './VersionCard'

export function UpdatesSection() {
  const t = useT()
  const { data, isPending } = useAllUpdates()
  const [q, setQ] = React.useState('')
  const needle = q.trim().toLowerCase()
  // "Show me" in a version's notes spotlights the feature, as in What's new.
  const onLink = showcaseLink(useTour.getState().start)
  const entries = (data?.entries || []).filter((e) => !needle || `${e.version} ${e.label} ${e.body}`.toLowerCase().includes(needle))
  return (
    <SectionStack>
      <VersionCard />
      <SettingsCard title={t('updates.title')} description={t('updates.desc', { count: data?.entries.length ?? 0 })}>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('updates.search')} className="pl-8" aria-label={t('updates.search')} />
          </div>
          {isPending ? (
            <div className="grid gap-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-20" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-20" />
            </div>
          ) : entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('updates.none')}</p>
          ) : (
            <ol className="grid grid-cols-[minmax(0,1fr)] gap-6" data-testid="updates-list">
              {entries.map((e) => (
                <li key={e.version} className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 border-l-2 pl-4 data-[current=true]:border-primary" data-current={e.current}>
                  <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-semibold [overflow-wrap:anywhere]">
                    <span className="tabular-nums">{e.version}</span>
                    {e.label && <span className="font-normal text-muted-foreground">{e.label}</span>}
                    {e.current && <Badge variant="success">{t('updates.installed')}</Badge>}
                  </h3>
                  <Markdown onLink={onLink} className={`min-w-0 text-[13.5px] [overflow-wrap:anywhere] ${SHOW_LINK_CLASS}`}>
                    {showLinks(e.body, t('show.button'))}
                  </Markdown>
                </li>
              ))}
            </ol>
          )}
        </div>
      </SettingsCard>
    </SectionStack>
  )
}
