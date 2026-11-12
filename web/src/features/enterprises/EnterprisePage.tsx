// One enterprise: a header (emoji, name) and its tabs (ENTERPRISE_TABS) as links, so the URL says which one is open.
import { Link, Navigate, NavLink, useParams } from 'react-router'
import { ArrowLeft, Building2 } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { enterpriseRoute, useEnterprise } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Button, EmptyState, Sensitive, Skeleton } from '@/components/ui'
import { PageBody, PageHeader } from '@/components/shell/Page'
import { ENTERPRISE_TABS } from './tabs'

export default function EnterprisePage() {
  const t = useT()
  const { id = '', tab } = useParams()
  const { data: e, isLoading, error, refetch } = useEnterprise(id)
  const tabs = ENTERPRISE_TABS
  const current = tabs.find((x) => x.id === (tab || tabs[0].id))
  if (tab && !current) return <Navigate to={enterpriseRoute(id)} replace />
  const back = (
    <Button asChild variant="ghost" size="icon-sm" aria-label={t('ent.back')} className="-ml-1">
      <Link to="/enterprises">
        <ArrowLeft />
      </Link>
    </Button>
  )
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="enterprise-page">
      <PageHeader
        leading={back}
        title={e ? <Sensitive length={12}>{`${e.emoji ? `${e.emoji} ` : ''}${e.name}`}</Sensitive> : t('ent.title')}
        sensitiveTitle={e?.name}
        description={e ? t('ent.page.desc', { projects: e.projects.length, positions: e.positions.length }) : undefined}
      />
      <PageBody width="wide">
        {isLoading ? (
          <div className="grid gap-4">
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-80 rounded-xl" />
          </div>
        ) : error || !e ? (
          <EmptyState
            tone="error"
            icon={Building2}
            title={t('ent.notFound')}
            description={errorMessage(error)}
            action={
              <Button variant="outline" onClick={() => void refetch()}>
                {t('common.retry')}
              </Button>
            }
          />
        ) : (
          <div className="grid gap-5">
            <nav aria-label={t('ent.tabs')} className="-mb-px flex gap-1 overflow-x-auto border-b">
              {tabs.map((x, i) => (
                <NavLink
                  key={x.id}
                  to={enterpriseRoute(id, i === 0 ? '' : x.id)}
                  end
                  className={({ isActive }) =>
                    cn(
                      'inline-flex h-10 shrink-0 items-center border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-md:h-12',
                      isActive && 'border-primary text-foreground',
                    )
                  }
                >
                  {t(x.label)}
                </NavLink>
              ))}
            </nav>
            {current?.render(e)}
          </div>
        )}
      </PageBody>
    </div>
  )
}
