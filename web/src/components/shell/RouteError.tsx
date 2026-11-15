import * as React from 'react'
import { isRouteErrorResponse, useNavigate, useRouteError } from 'react-router'
import { FileQuestion, RefreshCw, Sparkles, TriangleAlert } from 'lucide-react'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'
import { useDocumentTitle } from './Page'
import { BootReady } from '@/lib/bootLoader'
import { isChunkError, reloadForUpdate } from '@/lib/updateReload'

/** Route-level error boundary (chunk load failure after an update, render crash, 404). */
export function RouteError() {
  const t = useT()
  const err = useRouteError()
  const navigate = useNavigate()
  const notFound = isRouteErrorResponse(err) && err.status === 404
  const chunk = isChunkError(err) || (err instanceof Error && /Failed to fetch/i.test(err.message))
  // a page of the previous build (the server was updated while the app stayed open): reload by itself, once a minute
  // at most; until then, and if that did not help, a calm "new version" screen, not an error
  const [reloading] = React.useState(() => chunk && reloadForUpdate())
  if (import.meta.env.DEV) console.error(err)
  return (
    <div className="flex min-h-[70vh] flex-1 items-center justify-center p-6">
      <BootReady />
      <EmptyState
        icon={notFound ? FileQuestion : chunk ? Sparkles : TriangleAlert}
        tone={notFound || chunk ? 'default' : 'error'}
        title={notFound ? t('error.notFound') : chunk ? t('error.updated') : t('error.title')}
        description={notFound ? t('error.notFoundDesc') : chunk ? t(reloading ? 'error.updating' : 'error.updatedDesc') : err instanceof Error ? err.message : t('error.desc')}
        action={
          reloading ? null : notFound ? (
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
  useDocumentTitle(t('error.notFound'))
  return (
    <div className="flex min-h-[70vh] flex-1 items-center justify-center p-6">
      <EmptyState icon={FileQuestion} title={t('error.notFound')} description={t('error.notFoundDesc')} action={<Button onClick={() => navigate('/')}>{t('error.home')}</Button>} />
    </div>
  )
}
