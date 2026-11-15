// Settings -> Browser, ?profile=<id>: a profile (one per project, `main` = the person's, more added by hand). At the top its name
// (renamed in place) and its connection (with the address sites see). Then its persistent browsers (one per agent on
// it, a live picture each), the journal of its temporary ones (the sessions': text only), and its settings (what to
// do when the connection is down, memory, forget its sign-ins, delete).
import * as React from 'react'
import { Link } from 'react-router'
import { Bot, Globe, MessageSquare, User } from 'lucide-react'
import { useLang, useT } from '@/i18n'
import { useBrowserProfile, useBrowserStatus, useSaveBrowserProfile } from '@/lib/queries'
import type { BrowserNavigator, BrowserSessionLine } from '@/lib/types'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Button, Skeleton } from '@/components/ui'
import { openMyBrowser } from './open'
import { AsleepScene } from './AsleepScene'
import { BrowserWindow } from './BrowserWindow'
import { ConnectionPicker } from './ConnectionPicker'
import { ProfileSettings } from './ProfileSettings'
import { navName, ownerParts, profileName } from './profiles'
import { useNavPicture } from './useNavPicture'

export function ProfilePage({ pid }: { pid: string }) {
  const t = useT()
  const { data: v } = useBrowserProfile(pid)
  const { data: st } = useBrowserStatus()
  const save = useSaveBrowserProfile()
  const [name, setName] = React.useState('')
  const [win, setWin] = React.useState<{ nav: string; who: string } | null>(null)
  React.useEffect(() => setName(v?.profile.name || ''), [v?.profile.name])
  if (!v) return <Skeleton className="m-4 h-64" />
  const p = v.profile
  const where = p.id === 'main' ? t('browser.profile.yours') : p.project ? (v.gone ? t('browser.profile.projectGone') : t('browser.profile.ofProject', { name: p.project.slice(9) })) : ''
  const me = v.person[0]
  return (
    <div className="grid content-start gap-6" data-testid="browser-profile-page">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          placeholder={profileName({ id: p.id, name: '' }, t)}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() !== p.name && (name.trim() || p.id === 'main') && save.mutate({ id: p.id, name: name.trim() })}
          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
          maxLength={40}
          aria-label={t('browser.profile.rename')}
          title={t('browser.profile.rename')}
          className="h-8 w-full min-w-0 rounded-md border sm:w-56 pointer-coarse:h-10 border-transparent bg-transparent px-2 text-sm font-semibold outline-none hover:border-border focus:border-ring"
          data-testid="browser-profile-name"
        />
        {where && <span className="truncate text-[12px] text-muted-foreground">{where}</span>}
        <span className="flex-1" />
        <ConnectionPicker pid={p.id} note />
      </div>
      <div className="grid content-start gap-8">
        <section className="grid gap-3" data-testid="browser-persistent">
          <Heading title={t('browser.persistent')} desc={t('browser.persistentDesc')} />
          {me && (
            <button type="button" onClick={() => openMyBrowser()} className="inline-flex items-center gap-1.5 justify-self-start text-[12px] text-muted-foreground hover:text-foreground">
              <User className="size-3.5" /> {t('browser.persistentYou')}
            </button>
          )}
          {v.agents.length ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
              {v.agents.map((n) => (
                <AgentCard key={n.id} n={n} pid={p.id} onOpen={() => setWin({ nav: n.id, who: navName(n, t) })} />
              ))}
            </div>
          ) : (
            <EmptyCard icon={Bot} title={t('browser.persistentNone')} text={t('browser.persistentEmpty')}>
              <Button asChild size="sm" variant="outline">
                <Link to="/agents">{t('browser.mine.toAgents')}</Link>
              </Button>
            </EmptyCard>
          )}
        </section>
        <section className="grid gap-3" data-testid="browser-temporary">
          <Heading title={t('browser.temporary')} desc={t('browser.temporaryDesc')} />
          {v.temporary.length ? (
            <Journal rows={v.temporary} onWatch={(r) => setWin({ nav: `session:${r.session}`, who: r.title })} />
          ) : (
            <EmptyCard icon={MessageSquare} title={t('browser.temporaryNone')} text={t('browser.temporaryEmpty')} />
          )}
        </section>
        <section className="grid gap-3 border-t pt-6">
          <Heading title={t('browser.profile.settings')} />
          <ProfileSettings key={p.id} pid={p.id} />
        </section>
      </div>
      {win && st && (
        <BrowserWindow open onOpenChange={(o) => !o && setWin(null)} profile={p.id} nav={win.nav} who={win.who} start />
      )}
    </div>
  )
}

/** Nothing here yet: what would be here and how it comes (a dashed card, an action under it). */
export function EmptyCard({ icon: Icon, title, text, children }: { icon: React.ComponentType<{ className?: string }>; title: string; text: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-dashed p-4" data-testid="browser-empty">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4.5" />
      </span>
      <div className="grid min-w-0 gap-1">
        <p className="text-[13px] font-medium">{title}</p>
        <p className="text-[12px] leading-relaxed text-muted-foreground">{text}</p>
        {children && <div className="mt-1.5 flex flex-wrap gap-2">{children}</div>}
      </div>
    </div>
  )
}

function Heading({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="grid gap-0.5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {desc && <p className="text-[12px] text-muted-foreground">{desc}</p>}
    </div>
  )
}

/** An agent's persistent browser: a live picture while it runs, its page, "Claude is acting". */
export function AgentCard({ n, pid, onOpen }: { n: BrowserNavigator; pid: string; onOpen: () => void }) {
  const t = useT()
  const src = useNavPicture(pid, n.id, n.running && n.awake > 0, 3000, 480)
  const where = n.path ? ownerParts(n.path).where : ''
  return (
    <button type="button" onClick={onOpen} className="group grid min-w-0 overflow-hidden rounded-lg border bg-card text-left hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" data-testid="browser-agent-card">
      <div className="relative grid aspect-[16/10] place-items-center overflow-hidden bg-fill-1">
        {src ? (
          <img src={src} alt={n.page?.title || t('browser.page')} className="size-full object-cover object-top" draggable={false} />
        ) : n.running && n.awake > 0 ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Globe className="size-4 opacity-60" /> {t('browser.loading')}
          </span>
        ) : (
          <AsleepScene project={n.path || ''} label={t('browser.card.asleep')} />
        )}
        {n.turns > 0 && (
          <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1.5 rounded-full bg-background/90 px-2 py-0.5 text-[11px] text-muted-foreground shadow-xs">
            <span className="size-1.5 animate-pulse rounded-full bg-primary" /> {t('browser.claudeDriving')}
          </span>
        )}
      </div>
      <div className="grid min-w-0 gap-0.5 px-2.5 py-1.5">
        <span className="flex min-w-0 items-center gap-1.5 text-[13px] font-medium">
          <Bot className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{navName(n, t)}</span>
          {where && <span className="truncate text-[11px] font-normal text-muted-foreground">· {where}</span>}
        </span>
        <span className={cn('truncate text-[11px] text-muted-foreground', !n.page && 'italic')}>{n.page?.title || n.page?.url || t('browser.card.noTab')}</span>
      </div>
    </button>
  )
}

/** The temporary browsers: one line per session (text only). */
function Journal({ rows, onWatch }: { rows: BrowserSessionLine[]; onWatch: (r: BrowserSessionLine) => void }) {
  const t = useT()
  const lang = useLang()
  const cell = 'px-2.5 py-2 align-top'
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[36rem] text-[13px]">
        <thead className="bg-fill-1 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className={cn(cell, 'font-medium')}>{t('browser.temp.session')}</th>
            <th className={cn(cell, 'font-medium')}>{t('browser.temp.topic')}</th>
            <th className={cn(cell, 'font-medium')}>{t('browser.temp.sites')}</th>
            <th className={cn(cell, 'font-medium')}>{t('browser.temp.when')}</th>
            <th className={cn(cell, 'font-medium')}>{t('browser.temp.duration')}</th>
            <th className={cell} />
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => {
            const topic = r.path ? ownerParts(r.path).name : ''
            const min = Math.max(1, Math.round((r.last - r.first) / 60))
            return (
              <tr key={r.session} data-testid="browser-temp-row">
                <td className={cell}>
                  <Link to={`/sessions/${r.session}`} className="inline-flex max-w-64 items-center gap-1.5 hover:underline">
                    {r.open && <span className={cn('size-1.5 shrink-0 rounded-full', r.turns ? 'animate-pulse bg-primary' : 'bg-success')} />}
                    <span className="truncate">{r.title || t('browser.temp.untitled')}</span>
                  </Link>
                </td>
                <td className={cn(cell, 'text-muted-foreground')}>{topic}</td>
                <td className={cn(cell, 'max-w-72 truncate text-muted-foreground')} title={r.sites.join(', ')}>
                  {r.sites.slice(0, 3).join(', ')}
                  {r.sites.length > 3 ? ` (+${r.sites.length - 3})` : ''}
                </td>
                <td className={cn(cell, 'whitespace-nowrap text-muted-foreground')}>{r.open && r.turns ? t('browser.nav.acting') : fmtRelative(r.last, lang)}</td>
                <td className={cn(cell, 'whitespace-nowrap text-muted-foreground')}>{r.actions ? `${min} min` : '—'}</td>
                <td className={cn(cell, 'text-right')}>
                  {r.open && (
                    <Button size="sm" variant="outline" className="h-7" onClick={() => onWatch(r)}>
                      {t('browser.temp.watch')}
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
