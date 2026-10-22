// Boot gate: GET /api/auth/state decides where the user may go.
//   setup_required            → /setup (token kept from the query string)
//   !authenticated            → /login?next=<current location>
//   !onboarding_completed     → /welcome
//   authenticated on /login|/setup → next or /
import * as React from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuthState } from '@/lib/queries'
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { Button, EmptyState } from '@/components/ui'
import { LogoMark } from '@/components/shell/Logo'
import { WifiOff } from 'lucide-react'

const PUBLIC = ['/setup', '/login']

export function Root() {
  const t = useT()
  const loc = useLocation()
  const { data, isError, refetch, isFetching } = useAuthState()
  const setLanguage = useUI((s) => s.setLanguage)
  const langSynced = React.useRef(false)
  React.useEffect(() => {
    // Before sign-in the server language is the only hint (set in onboarding); afterwards settings rule.
    if (data?.language && !langSynced.current) {
      langSynced.current = true
      if (!data.authenticated) setLanguage(data.language)
      // A browser that never picked a theme (new device, private window) shows the last one chosen - the
      // sign-in page included.
      if (data.look && !useUI.getState().lookChosen) useUI.getState().adoptLook(data.look)
    }
  }, [data, setLanguage])

  if (isError && !data)
    return (
      <div className="flex h-dvh items-center justify-center p-6">
        <EmptyState
          icon={WifiOff}
          tone="error"
          title={t('boot.offline')}
          description={t('boot.offlineDesc')}
          action={
            <Button loading={isFetching} onClick={() => refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      </div>
    )
  if (!data) return <AuthLayoutFallback />

  const path = loc.pathname
  const here = path + loc.search
  if (data.setup_required) {
    if (path !== '/setup') return <Navigate to="/setup" replace />
    return <Outlet />
  }
  if (!data.authenticated) {
    if (path === '/login') return <Outlet />
    const next = PUBLIC.includes(path) || path === '/' ? '' : `?next=${encodeURIComponent(here)}`
    return <Navigate to={`/login${next}`} replace />
  }
  if (PUBLIC.includes(path)) {
    const next = new URLSearchParams(loc.search).get('next')
    const safe = next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
    return <Navigate to={data.onboarding_completed ? safe : '/welcome'} replace />
  }
  if (!data.onboarding_completed && path !== '/welcome' && !path.startsWith('/docs')) return <Navigate to="/welcome" replace />
  return <Outlet />
}

/** Neutral boot screen: same footprint as the splash in index.html, so the logo never moves or blinks. */
export function AuthLayoutFallback() {
  return (
    <div className="flex h-dvh items-center justify-center">
      <LogoMark className="size-10 animate-shimmer" />
    </div>
  )
}
