// A project, a topic or an agent and the Harness Browser: may its turns use it (a project or a topic can inherit the
// switch, an agent always chooses), which profile (sessions: their project's; an agent: its project's unless it picks
// another), where that profile's pages go out, "Open the browser" (BrowserWindow on that profile). Profiles and
// connections themselves are set up on the Browser page.
import * as React from 'react'
import { Link } from 'react-router'
import { useT } from '@/i18n'
import { useBrowserOwner, useBrowserStatus, useSaveBrowserOwner } from '@/lib/queries'
import type { BrowserOwner } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, Select, Skeleton, Switch } from '@/components/ui'
import { Callout, SettingRow } from '@/features/common'
import { BrowserWindow } from './BrowserWindow'
import { exitLine, exitName, exitTone, ownerParts, profileName } from './profiles'

const INHERIT = '__inherit'

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
  const projectProfile = profiles.find((p) => p.id === o.project_profile)
  const projectName = projectProfile ? profileName(projectProfile, t) : o.project.slice(9)
  const current = profiles.find((p) => p.id === o.profile)

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4" data-testid="browser-panel">
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
        {agent && (
          <SettingRow label={t('browser.signins.label')} description={t('browser.signins.desc')} htmlFor="br-profile">
            <AgentProfilePicker o={o} id="br-profile" className="w-56" />
          </SettingRow>
        )}
      </div>
      {!agent && <p className="break-words text-[12px] text-muted-foreground">{t('browser.panel.projectProfile', { name: projectName })}</p>}

      <div className="grid gap-2">
        <p className="flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground">
          <span className={cn('size-1.5 shrink-0 rounded-full', exitTone(o.exit || undefined))} />
          <span className="min-w-0 truncate">
            {t('browser.ownerLine', {
              profile: current ? profileName(current, t) : projectName,
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
            <Link to={`/settings/browser?profile=${encodeURIComponent(o.profile || o.project_profile)}`} className="text-[12px] text-muted-foreground underline-offset-2 hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-10 pointer-coarse:items-center">
              {t('browser.profile.settingsLink')}
            </Link>
          </div>
        )}
      </div>
      {o.enabled && live && <BrowserWindow context={path} profile={o.profile} who={who} open={win} onOpenChange={setWin} start />}
    </div>
  )
}

/** An agent's profile: its project's (the default: shared with the project's sessions and agents) or another one. */
export function AgentProfilePicker({ o, id, className }: { o: BrowserOwner; id?: string; className?: string }) {
  const t = useT()
  const { data: st } = useBrowserStatus(o.feature)
  const save = useSaveBrowserOwner()
  const profiles = st?.profiles || []
  const projectProfile = profiles.find((p) => p.id === o.project_profile)
  const projectName = projectProfile ? profileName(projectProfile, t) : o.project.slice(9)
  const value = o.own.profile && o.own.profile !== o.project_profile && profiles.some((p) => p.id === o.own.profile) ? o.own.profile : INHERIT
  return (
    <Select
      id={id}
      className={className}
      aria-label={t('browser.agent.profile')}
      value={value}
      onValueChange={(v) => save.mutate(v === INHERIT ? { path: o.path, inherit: ['profile'] } : { path: o.path, profile: v })}
      options={[
        { value: INHERIT, label: t('browser.signins.inherit', { name: projectName }) },
        ...profiles.filter((p) => p.id !== o.project_profile).map((p) => ({ value: p.id, label: profileName(p, t) })),
      ]}
      data-testid="browser-profile"
    />
  )
}
