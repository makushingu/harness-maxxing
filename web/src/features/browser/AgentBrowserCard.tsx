// An agent's browser (its persistent navigator) in its info panel: a small live picture of its tab (a new one every
// 2 s, only while the panel is shown and the browser runs: never started for it), the page, "Claude is acting" and its
// requests to the person; under it, its profile (its project's by default, or another) and, in its sandbox, its
// domains (the only sites it opens). A click opens the browser window to watch or take over. Nothing when its browser
// is off.
import * as React from 'react'
import { Globe, Hand, ShieldCheck } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserOwner, useBrowserStatus } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { AsleepScene } from './AsleepScene'
import { AgentProfilePicker } from './BrowserPanel'
import { BrowserWindow } from './BrowserWindow'
import { navOf } from './profiles'
import { useNavPicture } from './useNavPicture'

export function AgentBrowserCard({ path, who, title }: { path: string; who: string; title: string }) {
  const t = useT()
  const { data: o } = useBrowserOwner(path)
  const on = !!o?.feature && !!o?.enabled
  const { data: st } = useBrowserStatus(on)
  const [win, setWin] = React.useState(false)
  const id = navOf(undefined, path)
  const n = st?.navigators.find((x) => x.id === id)
  const running = !!n?.running
  const pid = n?.profile || o?.profile || ''
  const src = useNavPicture(pid, id, on && running)
  if (!on || !o) return null
  const tab = n?.page
  const asks = o.asks.length
  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2" data-testid="agent-browser-card">
      <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      <button type="button" onClick={() => setWin(true)} className="group grid min-w-0 overflow-hidden rounded-lg border bg-card text-left hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <div className="relative grid aspect-[16/10] place-items-center overflow-hidden bg-fill-1">
          {running && src ? (
            <img src={src} alt={tab?.title || t('browser.page')} className="size-full object-cover object-top" draggable={false} />
          ) : running ? (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <Globe className="size-4 opacity-60" /> {t('browser.loading')}
            </span>
          ) : (
            <AsleepScene project={path} label={t('browser.card.asleep')} />
          )}
          {running && !!n?.turns && (
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
      <AgentProfilePicker o={o} className="h-8 w-full text-[12px]" />
      {o.sites && (
        <p className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground" title={o.sites.join(', ')} data-testid="agent-browser-domains">
          <ShieldCheck className="size-3.5 shrink-0" />
          <span className="truncate">{o.sites.length ? t('browser.card.domains', { count: o.sites.length }) : t('browser.card.noDomain')}</span>
        </p>
      )}
      <BrowserWindow context={path} profile={pid} nav={id} who={who} open={win} onOpenChange={setWin} start />
    </section>
  )
}
