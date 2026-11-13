// /browser: the Harness Browser in the whole page (Settings -> Features -> Harness Browser). ?session=<id> shows that
// session's tab (the link of a request, "needs you in its browser"). Opening the page starts a stopped browser.
import { Link, useSearchParams } from 'react-router'
import { Settings2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useSettings } from '@/lib/queries'
import { Button } from '@/components/ui'
import { Callout } from '@/features/common'
import { LiveView } from './LiveView'

export default function BrowserPage() {
  const t = useT()
  const [params] = useSearchParams()
  const { data: s } = useSettings()
  const session = params.get('session') || undefined
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="browser-page">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{t('browser.name')}</h1>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/settings/features" data-testid="browser-page-settings">
            <Settings2 /> {t('browser.settingsLink')}
          </Link>
        </Button>
      </div>
      {s && !s.browser_feature ? (
        <div className="p-4">
          <Callout tone="info">
            {t('browser.featureOff')}{' '}
            <Link to="/settings/features" className="text-primary underline">
              {t('browser.openFeatures')}
            </Link>
          </Callout>
        </div>
      ) : (
        <LiveView key={session || 'page'} session={session} start className="min-h-0 flex-1" />
      )}
    </div>
  )
}
