import { isRouteErrorResponse, useNavigate, useRouteError } from 'react-router'
import { FileQuestion, RefreshCw, TriangleAlert } from 'lucide-react'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'

/** Route-level error boundary (chunk load failure after an update, render crash, 404). */
export function RouteError() {
  const t = useT()
  const err = useRouteError()
  const navigate = useNavigate()
  const notFound = isRouteErrorResponse(err) && err.status === 404
  const chunk = err instanceof Error && /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(err.message)
  if (import.meta.env.DEV) console.error(err)
  return (
    <div className="flex min-h-[70vh] flex-1 items-center justify-center p-6">
      <EmptyState
        icon={notFound ? FileQuestion : TriangleAlert}
        tone={notFound ? 'default' : 'error'}
        title={notFound ? t('error.notFound') : chunk ? t('error.updated') : t('error.title')}
        description={notFound ? t('error.notFoundDesc') : chunk ? t('error.updatedDesc') : err instanceof Error ? err.message : t('error.desc')}
        action={
          notFound ? (
            <Button onClick={() => navigate('/')}>{t('error.home')}</Button>
          ) : (
            <Button onClick={() => window.location.reload()}>
              <RefreshCw /> {t('error.reload')}
            </Button>
          )
        }
      />
    </div>
  )
}

export function NotFound() {
  const t = useT()
  const navigate = useNavigate()
  return (
    <div className="flex min-h-[70vh] flex-1 items-center justify-center p-6">
      <EmptyState icon={FileQuestion} title={t('error.notFound')} description={t('error.notFoundDesc')} action={<Button onClick={() => navigate('/')}>{t('error.home')}</Button>} />
    </div>
  )
}
