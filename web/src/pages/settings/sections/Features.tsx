// Settings > Features (2.0.0a132): every page of the sidebar in its order, the ones always there marked so and the
// optional ones with their switch; the options of the sessions sit indented under Sessions ("Tell me when a session
// finishes" lives in Notifications only), the Team bubbles under Team while Team is on, the agent preview on hover under Agents while Agents is on. A "This browser" mark tells the few
// switches kept in this browser only from those saved on the server.
import { useUI } from '@/stores/ui'
import { useT } from '@/i18n'
import { useSaveSettings, useSettings } from '@/lib/queries'
import { Skeleton, Switch } from '@/components/ui'
import { Checkbox } from '@/components/ui/checkbox'
import { Callout, SettingRow } from '@/features/common'
import { BrowserBadge, FeaturePages } from '@/features/settings/FeaturePages'
import { useSessionsUI } from '@/pages/sessions/store'
import { useTeamUI } from '@/features/team/store'
import { RESULT_FIELDS, useResultLine } from '@/pages/sessions/resultLine'
import { SettingsCard, SectionStack } from './ui'

export function FeaturesSection() {
  const t = useT()
  const ui = useUI()
  const { data: s } = useSettings()
  const save = useSaveSettings()
  const tabs = useSessionsUI((x) => x.tabs)

  // the options of the sessions, indented under the Sessions row
  const sessionOptions = !s ? (
    <Skeleton className="h-36" />
  ) : (
    <div className="divide-y [&>*:first-child]:pt-0">
      <SettingRow label={t('features.maxxing')} description={t('features.maxxingDesc')} htmlFor="ft-maxxing">
        <Switch id="ft-maxxing" checked={!!s.maxxing_mode} onCheckedChange={(v) => save.mutate({ maxxing_mode: v })} />
      </SettingRow>
      <SettingRow label={<>{t('features.tabs')}<BrowserBadge /></>} description={t('features.tabsDesc')} htmlFor="ft-tabs">
        <Switch id="ft-tabs" checked={tabs} onCheckedChange={(v) => useSessionsUI.getState().setTabs(v)} />
      </SettingRow>
      <SettingRow label={<>{t('hud.enable')}<BrowserBadge /></>} description={t('hud.enableDesc')} htmlFor="ft-hud">
        <Switch id="ft-hud" checked={ui.hud} onCheckedChange={ui.setHud} />
      </SettingRow>
      {ui.hud && !('documentPictureInPicture' in window) && (
        <div className="py-3">
          <Callout tone="info">{t('hud.fallback')}</Callout>
        </div>
      )}
      {/* was in General -> Appearance before 2.0.0a132; saved on the server */}
      <div className="grid gap-3 py-4 last:pb-0">
        <div className="grid gap-0.5">
          <span className="text-sm font-medium">{t('settings.resultLine')}</span>
          <p className="text-[13px] text-muted-foreground">{t('settings.resultLineDesc')}</p>
        </div>
        <ResultLinePicker />
      </div>
    </div>
  )

  // the Team bubbles (features/team/TeamBubbles.tsx), indented under the Team row while Team is on
  const teamOptions = s?.team_page ? (
    <SettingRow label={<>{t('team.bubblesSetting')}<BrowserBadge /></>} description={t('team.bubblesSettingDesc')} htmlFor="ft-team-bubbles">
      <Switch
        id="ft-team-bubbles"
        checked={ui.teamBubbles}
        onCheckedChange={(v) => {
          ui.setNotify({ teamBubbles: v })
          if (v) useTeamUI.getState().setHidden(false)
        }}
      />
    </SettingRow>
  ) : null

  // the agent card on hover (features/agents/AgentHover.tsx), indented under the Agents row while Agents is on
  const agentsOptions = s?.agents_page ? (
    <SettingRow label={<>{t('features.agentPreview')}<BrowserBadge /></>} description={t('features.agentPreviewDesc')} htmlFor="ft-agent-preview">
      <Switch id="ft-agent-preview" checked={ui.agentPreview} onCheckedChange={(v) => ui.setNotify({ agentPreview: v })} />
    </SettingRow>
  ) : null

  return (
    <SectionStack>
      <SettingsCard title={t('features.inSidebar')} description={t('features.pagesDesc')}>
        <FeaturePages core sub={{ '/sessions': sessionOptions, '/agents': agentsOptions, '/team': teamOptions }} />
      </SettingsCard>
    </SectionStack>
  )
}

function ResultLinePicker() {
  const t = useT()
  const { hidden, toggle } = useResultLine()
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2" data-testid="result-line-picker">
      {RESULT_FIELDS.map((f) => (
        <label key={f.id} className="flex cursor-pointer items-center gap-2 text-sm pointer-coarse:min-h-10">
          <Checkbox checked={!hidden.includes(f.id)} onCheckedChange={(c) => toggle(f.id, !!c)} />
          {t(f.label)}
        </label>
      ))}
    </div>
  )
}
