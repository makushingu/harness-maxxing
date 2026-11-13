// A project, a topic or an agent and the Harness Browser: may its turns use it (a project or a topic can inherit the
// switch, an agent always chooses), which profile (its own choice or inherited), where that profile's pages go out,
// "Open the browser" (BrowserWindow on that profile). Profiles and exits themselves are set up on the Browser page.
import * as React from 'react'
import { Link } from 'react-router'
import { TriangleAlert } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserOwner, useBrowserStatus, useSaveBrowserOwner } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Button, Select, Skeleton, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { BrowserWindow } from './BrowserWindow'
import { exitLine, exitName, exitTone, ownerParts, profileName } from './profiles'

const INHERIT = '__inherit'
const OWN = 'own'

export function BrowserPanel({ path, live = true, who }: { path: string; live?: boolean; who?: string }) {
  const t = useT()
  const { data: o, isLoading } = useBrowserOwner(path)
  const { data: st } = useBrowserStatus(!!o?.feature)
  const save = useSaveBrowserOwner()
  const [win, setWin] = React.useState(false)
  if (isLoading || !o) return <Skeleton className="h-24" />

  const agent = o.kind === 'agent'
  const parentName = (from: string) => (from ? ownerParts(from).name : t('browser.defaults'))
  const inh = o.inherited
  const switchValue = agent || o.own.enabled !== undefined ? (o.own.enabled ? 'on' : 'off') : INHERIT
  const profiles = st?.profiles || []
  const profileValue = agent && o.own_profile && o.own.profile === o.own_profile ? OWN : o.own.profile ? o.own.profile : INHERIT
  const inheritedProfile = inh ? profiles.find((p) => p.id === inh.profile) : profiles.find((p) => p.id === 'main')
  const current = profiles.find((p) => p.id === o.profile)

  return (
    <div className="grid min-w-0 gap-4" data-testid="browser-panel">
      {!o.feature && (
        <Callout tone="info">
          {t('browser.featureOff')}{' '}
          <Link to="/settings/features" className="text-primary underline">
            {t('browser.openFeatures')}
          </Link>
        </Callout>
      )}
      <div className="divide-y">
        {agent ? (
          <SettingRow label={t('browser.enable')} description={t('browser.enableDescAgent')} htmlFor="br-enabled">
            <Switch id="br-enabled" checked={o.enabled} onCheckedChange={(v) => save.mutate({ path, enabled: v })} data-testid="browser-enabled" />
          </SettingRow>
        ) : (
          <SettingRow label={t('browser.enable')} description={t(o.kind === 'project' ? 'browser.enableDescProject' : 'browser.enableDesc')} htmlFor="br-enabled">
            <Select
              id="br-enabled"
              className="w-48"
              value={switchValue}
              onValueChange={(v) => save.mutate(v === INHERIT ? { path, inherit: ['enabled'] } : { path, enabled: v === 'on' })}
              options={[
                { value: INHERIT, label: t('browser.inheritSwitch', { state: t(inh?.enabled ? 'browser.on' : 'browser.off'), from: parentName(inh?.from.enabled || '') }) },
                { value: 'on', label: t('browser.on') },
                { value: 'off', label: t('browser.off') },
              ]}
              data-testid="browser-enabled"
            />
          </SettingRow>
        )}
        <SettingRow
          label={t(agent ? 'browser.signins.label' : 'browser.profile.label')}
          description={t(agent ? 'browser.signins.desc' : 'browser.profile.ownerDesc')}
          htmlFor="br-profile"
        >
          <Select
            id="br-profile"
            className="w-56"
            value={profileValue}
            onValueChange={(v) => save.mutate(v === INHERIT ? { path, inherit: ['profile'] } : { path, profile: v })}
            options={[
              ...(agent ? [{ value: OWN, label: t('browser.signins.own') }] : []),
              { value: INHERIT, label: t(agent ? 'browser.signins.inherit' : 'browser.inheritProfile', { name: profileName(inheritedProfile || { id: inh?.profile || 'main', name: '' }, t) }) },
              ...profiles
                .filter((p) => !(agent && p.id === o.own_profile))
                .map((p) => ({ value: p.id, label: agent ? t('browser.signins.of', { name: profileName(p, t) }) : profileName(p, t) })),
            ]}
            data-testid="browser-profile"
          />
        </SettingRow>
      </div>

      {o.gone && (
        <Callout tone="warning" icon={TriangleAlert}>
          {t('browser.signins.gone')}
        </Callout>
      )}
      {o.outside_on_main && (
        <Callout tone="warning" icon={TriangleAlert}>
          {t('browser.outsideOnMain')}
        </Callout>
      )}

      <div className="grid gap-2">
        <p className="flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground">
          <span className={cn('size-1.5 shrink-0 rounded-full', exitTone(o.exit || undefined))} />
          <span className="min-w-0 truncate">
            {t('browser.ownerLine', {
              profile: profileName(current || { id: o.profile, name: '' }, t),
              exit: current ? exitName(current.exit, st?.exits, t) : '',
              line: o.exit ? exitLine(o.exit, t) : t('browser.exit.directLine'),
            })}
          </span>
        </p>
        {o.enabled && live && o.feature && (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setWin(true)} data-testid="browser-open-window">
              {t('browser.open')}
            </Button>
            <Link to={`/browser?profile=${encodeURIComponent(o.profile)}&view=settings`} className="text-[12px] text-muted-foreground underline-offset-2 hover:underline">
              {t('browser.profile.settingsLink')}
            </Link>
          </div>
        )}
      </div>
      {o.enabled && live && <BrowserWindow context={path} profile={o.profile} who={who} open={win} onOpenChange={setWin} start />}
    </div>
  )
}
