// An agent's browser in its info panel: a small live picture of its tab (a new one every 2 s, only while the panel
// is shown and the browser runs: never started for it), the page, "Claude is acting" and its requests to the person.
// A click opens the browser window to watch or take over. Nothing when its browser is off.
import * as React from 'react'
import { Globe, Hand, Moon } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserOwner, useBrowserProfile } from '@/lib/queries'
import { seg } from '@/lib/api'
import { cn } from '@/lib/utils'
import { BrowserWindow } from './BrowserWindow'

const EVERY_MS = 2000

export function AgentBrowserCard({ path, who, title }: { path: string; who: string; title: string }) {
  const t = useT()
  const { data: o } = useBrowserOwner(path)
  const on = !!o?.feature && !!o?.enabled
  const { data: view } = useBrowserProfile(o?.profile, on)
  const [win, setWin] = React.useState(false)
  const [src, setSrc] = React.useState<string | null>(null)
  const b = view?.browser
  const running = b?.state === 'running'
  const pid = o?.profile || ''

  // the picture: fetched while the page is visible and the browser runs; the previous one stays until the next
  React.useEffect(() => {
    if (!on || !running || !pid) {
      setSrc(null)
      return
    }
    let stop = false
    let url: string | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      if (stop) return
      if (document.visibilityState === 'visible') {
        try {
          const r = await fetch(`/api/browser/profiles/${seg(pid)}/picture?w=640&path=${encodeURIComponent(path)}`, { credentials: 'same-origin', cache: 'no-store' })
          if (r.status === 200 && !stop) {
            const next = URL.createObjectURL(await r.blob())
            if (url) URL.revokeObjectURL(url)
            url = next
            setSrc(next)
          }
        } catch {
          /* the next one */
        }
      }
      timer = setTimeout(tick, EVERY_MS)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
      if (url) URL.revokeObjectURL(url)
    }
  }, [on, running, pid, path])

  if (!on || !o) return null
  const mine = b?.tabs.filter((x) => x.by.path === path && !x.asleep) || []
  const tab = mine.sort((x, y) => (y.used || 0) - (x.used || 0))[0] || b?.tabs.find((x) => x.front)
  const asks = o.asks.length
  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2" data-testid="agent-browser-card">
      <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      <button type="button" onClick={() => setWin(true)} className="group grid min-w-0 overflow-hidden rounded-lg border bg-card text-left hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <div className="relative grid aspect-[16/10] place-items-center overflow-hidden bg-muted/40">
          {running && src ? (
            <img src={src} alt={tab?.title || t('browser.page')} className="size-full object-cover object-top" draggable={false} />
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
              {running ? <Globe className="size-4 opacity-60" /> : <Moon className="size-4 opacity-60" />}
              {running ? t('browser.loading') : t('browser.card.asleep')}
            </span>
          )}
          {running && b?.busy && (
            <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1.5 rounded-full bg-background/90 px-2 py-0.5 text-[11px] text-muted-foreground shadow-xs">
              <span className="size-1.5 animate-pulse rounded-full bg-primary" /> {t('browser.claudeDriving')}
            </span>
          )}
          {asks > 0 && (
            <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-1 rounded-full bg-background/90 px-2 py-0.5 text-[11px] font-medium text-warning shadow-xs ring-1 ring-warning/40">
              <Hand className="size-3" /> {t('browser.card.waits')}
            </span>
          )}
        </div>
        <div className="grid min-w-0 gap-0.5 px-2.5 py-1.5">
          <span className={cn('truncate text-[12px] font-medium', !tab && 'text-muted-foreground')}>{tab?.title || tab?.url || t('browser.card.noTab')}</span>
          {tab?.url && <span className="truncate font-mono text-[11px] text-muted-foreground">{tab.url}</span>}
        </div>
      </button>
      <BrowserWindow context={path} profile={o.profile} who={who} open={win} onOpenChange={setWin} start />
    </section>
  )
}
