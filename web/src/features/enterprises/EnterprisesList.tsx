// /enterprises: the enterprises as cards, and New enterprise.
import * as React from 'react'
import { Link } from 'react-router'
import { Building2, Plus } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { enterpriseRoute, useEnterprises } from '@/lib/queries'
import { Badge, Button, Card, EmptyState, Sensitive, Skeleton } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { NewEnterpriseDialog } from './dialogs'

export function EnterprisesList() {
  const t = useT()
  const { data, isLoading, error, refetch } = useEnterprises()
  const [creating, setCreating] = React.useState(false)
  const add = (
    <Button onClick={() => setCreating(true)} data-testid="enterprise-new-open">
      <Plus /> {t('ent.new.action')}
    </Button>
  )
  return (
    <Page title={t('ent.title')} description={t('ent.desc')} actions={data && data.length > 0 ? add : undefined}>
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <EmptyState
          tone="error"
          icon={Building2}
          title={t('ent.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : !data || data.length === 0 ? (
        <EmptyState icon={Building2} title={t('ent.empty')} description={t('ent.emptyDesc')} action={add} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="enterprise-list">
          {data.map((x) => (
            <li key={x.id} className="min-w-0">
              <Link to={enterpriseRoute(x.id)} className="block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring" data-testid="enterprise-card">
                <Card className="h-full gap-3 p-[var(--pad-card)] transition-colors hover:bg-accent">
                  <div className="flex items-center gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted/60 text-lg">
                      {x.emoji || <Building2 className="size-5 text-muted-foreground" strokeWidth={1.6} />}
                    </span>
                    <div className="grid min-w-0">
                      <span className="truncate text-[15px] font-medium">
                        <Sensitive length={10}>{x.name}</Sensitive>
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        <Sensitive length={12}>{x.projects.length ? x.projects.join(' · ') : t('ent.card.noProjects')}</Sensitive>
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>{t('ent.card.positions', { count: x.positions })}</span>
                    {x.vacant > 0 && <Badge variant="muted">{t('ent.card.vacant', { count: x.vacant })}</Badge>}
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <NewEnterpriseDialog open={creating} onOpenChange={setCreating} />
    </Page>
  )
}
