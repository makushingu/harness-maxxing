import * as React from 'react'
import { onlineManager } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import type { SSEStatus } from '@/lib/sse'
import { useT } from '@/i18n'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/utils'

const SHOW_AFTER = 1200 // ms: short network blips stay invisible
const BACK_FOR = 2000

/** Is the server itself down (restart, update) - as opposed to a sign-in or proxy problem? */
async function serverDown(): Promise<boolean> {
  try {
    const r = await fetch('/api/auth/state', { cache: 'no-store', credentials: 'same-origin' })
    return r.status === 502 || r.status === 503 || r.status === 504
  } catch {
    return true
  }
}

/**
 * Pill at the top while the live connection to the server is lost (server restarting after an
 * update, VPS reboot). Queries are paused meanwhile, so pages keep their data instead of showing
 * errors, and everything refreshes when the connection is back.
 */
export function ConnectionBanner({ status }: { status: SSEStatus }) {
  const t = useT()
  const [state, setState] = React.useState<'hidden' | 'down' | 'back'>('hidden')
  const shown = React.useRef(false)

  React.useEffect(() => {
    if (status === 'reconnecting') {
      let cancelled = false
      const timer = setTimeout(async () => {
        if (cancelled || !(await serverDown()) || cancelled) return
        shown.current = true
        onlineManager.setOnline(false)
        setState('down')
      }, SHOW_AFTER)
      return () => {
        cancelled = true
        clearTimeout(timer)
      }
    }
    if (status === 'open' && shown.current) {
      shown.current = false
      onlineManager.setOnline(true)
      setState('back')
    }
  }, [status])

  // Own effect: a new blip during the "back" pill must not cancel the timer that hides it.
  React.useEffect(() => {
    if (state !== 'back') return
    const timer = setTimeout(() => setState('hidden'), BACK_FOR)
    return () => clearTimeout(timer)
  }, [state])

  React.useEffect(() => () => onlineManager.setOnline(true), [])

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'pointer-events-none fixed inset-x-0 top-[calc(var(--safe-top,0px)+64px)] z-[60] flex justify-center px-4 transition-all duration-300',
        state === 'hidden' ? '-translate-y-3 opacity-0' : 'translate-y-0 opacity-100',
      )}
    >
      {state !== 'hidden' && (
        <div className="pointer-events-auto flex items-center gap-3 rounded-full border bg-popover px-4 py-2 text-[13px] text-popover-foreground shadow-pop">
          {state === 'down' ? (
            <>
              <Spinner className="size-4 text-primary" />
              <span>
                <span className="font-medium">{t('conn.down')}</span>
                <span className="text-muted-foreground max-sm:hidden"> · {t('conn.downDesc')}</span>
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 className="size-4 text-success" />
              <span className="font-medium">{t('conn.back')}</span>
            </>
          )}
        </div>
      )}
    </div>
  )
}
