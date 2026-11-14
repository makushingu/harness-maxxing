// The person's browser at rest (Settings -> Browser): its picture (live while it runs, else asleep), what it is (a
// Chromium of the server), its profile and its connection, and "Open my browser" (its window); under it the agents'
// browsers. Opening it is a click, never the settings themselves: the live view starts Chromium.
import { Link } from 'react-router'
import { Bot, Globe, Monitor } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserNavigator } from '@/lib/queries'
import type { BrowserStatus } from '@/lib/types'
import { Button, Select } from '@/components/ui'
import { AsleepScene } from './AsleepScene'
import { ConnectionPicker } from './ConnectionPicker'
import { AgentCard, EmptyCard } from './ProfilePage'
import { orderedProfiles, profileName } from './profiles'
import { useNavPicture } from './useNavPicture'

export function MyBrowser({ st, pid, onOpen, onAgent }: { st: BrowserStatus; pid: string; onOpen: () => void; onAgent: (nav: string) => void }) {
  const t = useT()
  const move = useBrowserNavigator()
  const me = st.navigators.find((n) => n.id === 'me')
  const running = !!me?.running && me.awake > 0
  const src = useNavPicture(pid, 'me', running, 2000, 960)
  const agents = st.navigators.filter((n) => n.kind === 'agent')
  const page = me?.page && me.page.url !== 'about:blank' ? me.page : null
  return (
    <div className="grid content-start gap-8" data-testid="browser-mine">
      <div className="contents">
        <section className="grid gap-5 md:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] md:items-start">
          <button
            type="button"
            onClick={onOpen}
            className="group grid min-w-0 overflow-hidden rounded-xl border bg-card text-left hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            data-testid="browser-mine-picture"
          >
            <div className="relative grid aspect-[16/10] place-items-center overflow-hidden bg-fill-1">
              {running && page && src ? (
                <img src={src} alt={page.title || t('browser.page')} className="size-full object-cover object-top" draggable={false} />
              ) : running ? (
                <span className="grid justify-items-center gap-2 text-[13px] text-muted-foreground">
                  <Globe className="size-8 opacity-50" /> {t('browser.mine.ready')}
                </span>
              ) : (
                <AsleepScene project="" label={t('browser.mine.asleep')} size="lg" />
              )}
            </div>
            <div className="grid min-w-0 gap-0.5 px-3 py-2">
              <span className="truncate text-[13px] font-medium">{page?.title || page?.url || t('browser.mine.noPage')}</span>
              {page?.url && <span className="truncate font-mono text-[11px] text-muted-foreground">{page.url}</span>}
            </div>
          </button>
          <div className="grid content-start gap-5">
            <div className="grid gap-1.5">
              <p className="flex items-start gap-2 text-[13px] leading-relaxed">
                <Monitor className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span>{t('browser.mine.desc')}</span>
              </p>
            </div>
            <label className="grid gap-1.5">
              <span className="text-[12px] font-medium">{t('browser.menu.signins')}</span>
              <Select
                className="h-9 text-[13px]"
                aria-label={t('browser.menu.signins')}
                value={pid}
                onValueChange={(x) => x !== pid && move.mutate({ profile: x })}
                options={orderedProfiles(st.profiles, t).map((p) => ({ value: p.id, label: profileName(p, t) }))}
                data-testid="browser-mine-profile"
              />
              <span className="text-[12px] text-muted-foreground">{t('browser.mine.profileHint')}</span>
            </label>
            <div className="grid gap-1.5">
              <span className="text-[12px] font-medium">{t('browser.mine.connection')}</span>
              <ConnectionPicker pid={pid} note wide className="w-full" />
              <span className="text-[12px] text-muted-foreground">{t('browser.mine.connectionHint')}</span>
            </div>
            <Button className="justify-self-start" onClick={onOpen} data-testid="browser-mine-open">
              <Globe /> {t('browser.mine.open')}
            </Button>
          </div>
        </section>
        <section className="grid gap-3" data-testid="browser-mine-agents">
          <div className="grid gap-0.5">
            <h2 className="text-sm font-semibold">{t('browser.mine.agents')}</h2>
            <p className="text-[12px] text-muted-foreground">{t('browser.mine.agentsDesc')}</p>
          </div>
          {agents.length ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
              {agents.map((n) => (
                <AgentCard key={n.id} n={n} pid={n.profile || ''} onOpen={() => onAgent(n.id)} />
              ))}
            </div>
          ) : (
            <EmptyCard icon={Bot} title={t('browser.mine.noAgents')} text={t('browser.mine.noAgentsHow')}>
              <Button asChild size="sm" variant="outline">
                <Link to="/agents">{t('browser.mine.toAgents')}</Link>
              </Button>
            </EmptyCard>
          )}
        </section>
      </div>
    </div>
  )
}
