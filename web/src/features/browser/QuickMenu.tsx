// The ⋮ of the live view's toolbar: the settings one changes while browsing, without leaving the page. The profile this
// navigator uses (the person's browser and an agent's may switch; a session's is its project's), the profile's
// connection and its state, the search engine of the address bar, the picture (smooth / sharp /
// auto), forget the sign-ins. The Browser page keeps the rest (profiles, connections, their settings).
import { useNavigate } from 'react-router'
import { Check, Eraser, EllipsisVertical, Gauge, KeyRound, Search, Settings2, Waypoints } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserNavigator, useBrowserStatus, useProfileAction, useSaveBrowserOwner, useSaveBrowserProfile, useSaveBrowserSettings } from '@/lib/queries'
import type { BrowserSettings } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  Button, confirm, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui'
import { exitLine, exitName, exitTone, profileName } from './profiles'

export type Quality = 'auto' | 'high' | 'low'
const ENGINES: Record<BrowserSettings['search'], string> = { google: 'Google', duckduckgo: 'DuckDuckGo', bing: 'Bing' }

export function QuickMenu({ profile, nav, quality, onQuality }: {
  profile: string
  nav: string
  quality: Quality
  onQuality: (q: Quality) => void
}) {
  const t = useT()
  const go = useNavigate()
  const { data: st } = useBrowserStatus()
  const move = useBrowserNavigator()
  const owner = useSaveBrowserOwner()
  const saveProfile = useSaveBrowserProfile()
  const saveSettings = useSaveBrowserSettings()
  const action = useProfileAction()
  const p = st?.profiles.find((x) => x.id === profile)
  const exit = st?.exits.find((e) => e.id === p?.exit)
  const kind = nav.startsWith('agent:') ? 'agent' : nav.startsWith('session:') ? 'session' : 'person'
  const agentPath = kind === 'agent' ? nav.slice(6) : ''
  const choices = st?.profiles || []
  // an agent back on its project's profile: no choice of its own any more
  const projectOf = agentPath.split('/').slice(0, 2).join('/')
  const pick = (id: string) => {
    if (id === profile) return
    if (kind === 'person') move.mutate({ profile: id })
    else if (kind === 'agent') {
      const mine = choices.find((x) => x.project === projectOf)?.id === id
      owner.mutate(mine ? { path: agentPath, inherit: ['profile'] } : { path: agentPath, profile: id })
    }
  }
  const forget = async () => {
    if (!(await confirm({ title: t('browser.forgetTitle'), description: t('browser.forgetConfirm'), destructive: true }))) return
    action.mutate({ profile, action: 'forget' })
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" className="shrink-0" aria-label={t('browser.menu.title')} title={t('browser.menu.title')} data-testid="browser-menu">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{t('browser.menu.signins')}</DropdownMenuLabel>
        {kind === 'session' ? (
          <DropdownMenuItem onSelect={() => go(`/settings/browser?profile=${encodeURIComponent(profile)}`)}>
            <KeyRound /> <span className="min-w-0 flex-1 truncate">{profileName(p || { id: profile, name: '' }, t)}</span>
            <span className="text-[11px] text-muted-foreground">{t('browser.menu.ofFolder')}</span>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger data-testid="browser-menu-profile">
              <KeyRound /> <span className="min-w-0 flex-1 truncate">{profileName(p || { id: profile, name: '' }, t)}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-60">
              <DropdownMenuRadioGroup value={profile} onValueChange={pick}>
                {choices.map((x) => (
                  <DropdownMenuRadioItem key={x.id} value={x.id}>
                    <span className="truncate">{profileName(x, t)}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => go('/settings/browser?new=profile')}>{t('browser.profile.add')}</DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger data-testid="browser-menu-exit">
            <Waypoints />
            <span className="grid min-w-0 flex-1">
              <span className="truncate">{p ? exitName(p.exit, st?.exits, t) : ''}</span>
              <span className="flex min-w-0 items-center gap-1.5 truncate text-[11px] text-muted-foreground">
                <span className={cn('size-1.5 shrink-0 rounded-full', exitTone(exit))} /> {exitLine(exit, t)}
              </span>
            </span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-64">
            <DropdownMenuRadioGroup value={p?.exit || 'direct'} onValueChange={(x) => p && x !== p.exit && saveProfile.mutate({ id: profile, exit: x })}>
              <DropdownMenuRadioItem value="direct">{t('browser.exit.direct')}</DropdownMenuRadioItem>
              {(st?.exits || []).map((e) => (
                <DropdownMenuRadioItem key={e.id} value={e.id}>
                  <span className={cn('size-1.5 shrink-0 rounded-full', exitTone(e))} /> <span className="truncate">{e.name}</span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => go('/settings/browser?exit=new')}>{t('browser.exit.add')}</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        <DropdownMenuSeparator />
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Search /> <span className="min-w-0 flex-1 truncate">{t('browser.menu.search')}</span>
            <span className="text-[11px] text-muted-foreground">{st ? ENGINES[st.settings.search] : ''}</span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup value={st?.settings.search} onValueChange={(x) => saveSettings.mutate({ search: x as BrowserSettings['search'] })}>
              {Object.entries(ENGINES).map(([e, name]) => (
                <DropdownMenuRadioItem key={e} value={e}>
                  {name}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger data-testid="browser-menu-quality">
            <Gauge /> <span className="min-w-0 flex-1 truncate">{t('browser.menu.picture')}</span>
            <span className="text-[11px] text-muted-foreground">{t(`browser.quality.${quality}` as const)}</span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-64">
            {(['auto', 'low', 'high'] as Quality[]).map((q) => (
              <DropdownMenuItem key={q} onSelect={() => onQuality(q)} className="items-start">
                <Check className={cn('mt-0.5', q !== quality && 'invisible')} />
                <span className="grid min-w-0">
                  <span>{t(`browser.quality.${q}`)}</span>
                  <span className="text-[11px] text-muted-foreground">{t(`browser.quality.${q}Desc`)}</span>
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => go(`/settings/browser?profile=${encodeURIComponent(profile)}`)}>
          <Settings2 /> {t('browser.menu.manage')}
        </DropdownMenuItem>
        <DropdownMenuItem destructive onSelect={forget} data-testid="browser-menu-forget">
          <Eraser /> {t('browser.forget')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
